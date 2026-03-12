"""Picks API routes for LadderBot web dashboard.

Endpoints:
    GET  /api/picks/today         — Today's parlays with full leg details
    POST /api/picks/{id}/verify   — Verify FanDuel odds, recalculate edge
    POST /api/picks/{id}/place    — Mark parlay as placed
    POST /api/picks/{id}/skip     — Mark parlay as skipped
"""
import asyncio
import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

logger = logging.getLogger("ladderbot")

from ladderbot.db.database import get_db
from ladderbot.utils.odds import (
    american_to_decimal,
    decimal_to_american,
    implied_probability,
    calculate_edge,
    classify_confidence,
)


router = APIRouter(prefix="/api/picks", tags=["picks"])


# -- Pydantic models ----------------------------------------------------------


class VerifyRequest(BaseModel):
    fd_leg1_odds: int
    fd_leg2_odds: int
    fd_parlay_odds: int


class PlaceRequest(BaseModel):
    actual_odds: int
    actual_stake: float


class SkipRequest(BaseModel):
    reason: str = "user_choice"


class ResultRequest(BaseModel):
    result: str  # "won" or "lost"


# -- Helpers -------------------------------------------------------------------


def _get_conn(request: Request):
    """Get a DB connection using app-level db_path."""
    db_path = getattr(request.app.state, "db_path", None)
    return get_db(db_path)


def _get_config(request: Request) -> dict:
    """Get app config."""
    return getattr(request.app.state, "config", {})


def _row_to_dict(row) -> dict:
    """Convert sqlite3.Row to dict."""
    if row is None:
        return None
    return dict(row)


def _build_parlay_response(conn, parlay_row) -> dict:
    """Build a full parlay response with leg details."""
    p = _row_to_dict(parlay_row)
    if p is None:
        return None

    # Fetch leg details
    leg1 = None
    leg2 = None
    if p.get("leg1_pick_id"):
        row = conn.execute(
            """
            SELECT pk.*, g.sport, g.home_team, g.away_team, g.game_date, g.status as game_status,
                   mp.model_prob, mp.book_prob, mp.edge
            FROM picks pk
            JOIN games g ON pk.game_id = g.game_id
            LEFT JOIN model_predictions mp ON pk.game_id = mp.game_id
                AND pk.market = mp.market AND pk.outcome = mp.outcome
            WHERE pk.pick_id = ?
            """,
            (p["leg1_pick_id"],),
        ).fetchone()
        leg1 = _row_to_dict(row)

    if p.get("leg2_pick_id"):
        row = conn.execute(
            """
            SELECT pk.*, g.sport, g.home_team, g.away_team, g.game_date, g.status as game_status,
                   mp.model_prob, mp.book_prob, mp.edge
            FROM picks pk
            JOIN games g ON pk.game_id = g.game_id
            LEFT JOIN model_predictions mp ON pk.game_id = mp.game_id
                AND pk.market = mp.market AND pk.outcome = mp.outcome
            WHERE pk.pick_id = ?
            """,
            (p["leg2_pick_id"],),
        ).fetchone()
        leg2 = _row_to_dict(row)

    # Build confidence from edge
    confidence = classify_confidence(p.get("combined_edge", 0))

    return {
        "parlay_id": p["parlay_id"],
        "combined_odds": p["combined_odds"],
        "combined_edge": p["combined_edge"],
        "confidence": confidence,
        "result": p.get("result"),
        "payout": p.get("payout"),
        "placed": bool(p.get("placed", 0)),
        "placed_at": p.get("placed_at"),
        "skipped": bool(p.get("skipped", 0)),
        "skip_reason": p.get("skip_reason"),
        "actual_stake": p.get("actual_stake"),
        "fd_leg1_odds": p.get("fd_leg1_odds"),
        "fd_leg2_odds": p.get("fd_leg2_odds"),
        "fd_parlay_odds": p.get("fd_parlay_odds"),
        "fd_edge": p.get("fd_edge"),
        "created_at": p.get("created_at"),
        "leg1": leg1,
        "leg2": leg2,
    }


# -- Routes --------------------------------------------------------------------


@router.get("/today")
async def get_today_picks(request: Request):
    """Get today's parlays with full leg details."""
    conn = _get_conn(request)
    try:
        today = datetime.now().strftime("%Y-%m-%d")
        rows = conn.execute(
            """
            SELECT * FROM parlays
            WHERE date(created_at) = ?
            ORDER BY combined_edge DESC
            """,
            (today,),
        ).fetchall()

        parlays = []
        for row in rows:
            parlay = _build_parlay_response(conn, row)
            if parlay:
                parlays.append(parlay)

        # Also get current ladder state for context
        ladder = conn.execute(
            "SELECT * FROM ladder_state ORDER BY attempt_id DESC, step DESC LIMIT 1"
        ).fetchone()

        return {
            "date": today,
            "picks": parlays,
            "ladder": _row_to_dict(ladder),
        }
    finally:
        conn.close()


@router.post("/scan")
async def scan_for_picks(request: Request):
    """Run the pipeline on demand — fetch odds, detect edges, build parlays."""
    config = _get_config(request)

    from ladderbot.run import run_pipeline

    try:
        result = await asyncio.to_thread(
            run_pipeline, config, sport_filter=None, send_alerts=False
        )
    except Exception as exc:
        logger.exception("Pipeline scan failed")
        raise HTTPException(status_code=500, detail=f"Scan failed: {exc}")

    return {
        "status": "ok",
        "games_analyzed": result["games_analyzed"],
        "ev_bets_found": result["ev_bets_found"],
        "parlays_found": len(result["parlays"]),
    }


@router.post("/{parlay_id}/verify")
async def verify_odds(parlay_id: int, body: VerifyRequest, request: Request):
    """Verify FanDuel odds against DraftKings, recalculate edge.

    Accepts FD odds for both legs and the actual FD parlay odds.
    Returns the recalculated edge and a pass/fail verdict.
    """
    conn = _get_conn(request)
    config = _get_config(request)
    min_edge = config.get("parlay", {}).get("min_edge_per_leg", 0.02)

    try:
        parlay = conn.execute(
            "SELECT * FROM parlays WHERE parlay_id = ?", (parlay_id,)
        ).fetchone()

        if not parlay:
            raise HTTPException(status_code=404, detail="Parlay not found")

        p = _row_to_dict(parlay)

        # Get model probabilities for both legs
        leg1_model_prob = None
        leg2_model_prob = None

        if p.get("leg1_pick_id"):
            pick = conn.execute(
                "SELECT * FROM picks WHERE pick_id = ?", (p["leg1_pick_id"],)
            ).fetchone()
            if pick:
                pred = conn.execute(
                    """
                    SELECT model_prob FROM model_predictions
                    WHERE game_id = ? AND market = ? AND outcome = ?
                    ORDER BY timestamp DESC LIMIT 1
                    """,
                    (pick["game_id"], pick["market"], pick["outcome"]),
                ).fetchone()
                if pred:
                    leg1_model_prob = pred["model_prob"]

        if p.get("leg2_pick_id"):
            pick = conn.execute(
                "SELECT * FROM picks WHERE pick_id = ?", (p["leg2_pick_id"],)
            ).fetchone()
            if pick:
                pred = conn.execute(
                    """
                    SELECT model_prob FROM model_predictions
                    WHERE game_id = ? AND market = ? AND outcome = ?
                    ORDER BY timestamp DESC LIMIT 1
                    """,
                    (pick["game_id"], pick["market"], pick["outcome"]),
                ).fetchone()
                if pred:
                    leg2_model_prob = pred["model_prob"]

        # Calculate FD edge using actual FD parlay odds
        dk_combined_odds = p["combined_odds"]
        fd_combined_odds = body.fd_parlay_odds

        # DK edge (original)
        dk_edge = p["combined_edge"]

        # FD edge: use model probs if available, otherwise estimate from DK edge
        if leg1_model_prob is not None and leg2_model_prob is not None:
            fd_parlay_decimal = american_to_decimal(fd_combined_odds)
            fd_combined_prob = leg1_model_prob * leg2_model_prob
            fd_edge = (fd_combined_prob * fd_parlay_decimal) - 1
        else:
            # Fallback: adjust DK edge by odds difference
            dk_decimal = american_to_decimal(dk_combined_odds)
            fd_decimal = american_to_decimal(fd_combined_odds)
            dk_implied = 1 / dk_decimal
            fd_implied = 1 / fd_decimal
            fd_edge = dk_edge - (fd_implied - dk_implied)

        odds_diff = fd_combined_odds - dk_combined_odds
        still_plus_ev = fd_edge >= min_edge

        if still_plus_ev:
            verdict = "STILL +EV"
            message = (
                f"Edge reduced from {dk_edge*100:.1f}% to {fd_edge*100:.1f}% "
                f"— still above {min_edge*100:.1f}% threshold"
            )
            if fd_edge >= dk_edge:
                message = (
                    f"Edge improved from {dk_edge*100:.1f}% to {fd_edge*100:.1f}% "
                    f"— FD odds are better"
                )
        else:
            verdict = "EDGE GONE"
            message = (
                f"Edge dropped to {fd_edge*100:.1f}% "
                f"— below {min_edge*100:.1f}% threshold. Recommend SKIP."
            )

        return {
            "pick_id": parlay_id,
            "dk_parlay_odds": dk_combined_odds,
            "fd_parlay_odds": fd_combined_odds,
            "odds_diff": odds_diff,
            "dk_edge": round(dk_edge, 4),
            "fd_edge": round(fd_edge, 4),
            "still_plus_ev": still_plus_ev,
            "verdict": verdict,
            "message": message,
        }
    finally:
        conn.close()


@router.post("/{parlay_id}/place")
async def place_pick(parlay_id: int, body: PlaceRequest, request: Request):
    """Mark a parlay as placed with actual FanDuel odds and stake."""
    conn = _get_conn(request)
    try:
        parlay = conn.execute(
            "SELECT * FROM parlays WHERE parlay_id = ?", (parlay_id,)
        ).fetchone()

        if not parlay:
            raise HTTPException(status_code=404, detail="Parlay not found")

        p = _row_to_dict(parlay)

        if p.get("placed"):
            raise HTTPException(status_code=400, detail="Parlay already placed")
        if p.get("skipped"):
            raise HTTPException(status_code=400, detail="Parlay already skipped")

        # Use verified FD odds if available, otherwise keep what's stored
        fd_edge = p.get("fd_edge") or p["combined_edge"]

        # Update parlay as placed — only set fd_parlay_odds if not already set from /verify
        conn.execute(
            """
            UPDATE parlays SET
                placed = 1,
                placed_at = datetime('now'),
                actual_stake = ?,
                fd_parlay_odds = COALESCE(fd_parlay_odds, ?),
                fd_edge = COALESCE(fd_edge, ?)
            WHERE parlay_id = ?
            """,
            (body.actual_stake, body.actual_odds, fd_edge, parlay_id),
        )
        conn.commit()

        # Calculate potential payout
        decimal_odds = american_to_decimal(body.actual_odds)
        potential_payout = round(body.actual_stake * decimal_odds, 2)

        # Get ladder info
        ladder = conn.execute(
            "SELECT * FROM ladder_state ORDER BY attempt_id DESC, step DESC LIMIT 1"
        ).fetchone()
        ladder_step = ladder["step"] if ladder else 1

        # Calculate next step target
        config = _get_config(request)
        target = config.get("ladder", {}).get("target_amount", 1000.0)

        return {
            "pick_id": parlay_id,
            "status": "placed",
            "ladder_step": ladder_step,
            "potential_payout": potential_payout,
            "next_step_target": target,
        }
    finally:
        conn.close()


@router.post("/{parlay_id}/skip")
async def skip_pick(parlay_id: int, body: SkipRequest, request: Request):
    """Mark a parlay as skipped with a reason."""
    conn = _get_conn(request)
    try:
        parlay = conn.execute(
            "SELECT * FROM parlays WHERE parlay_id = ?", (parlay_id,)
        ).fetchone()

        if not parlay:
            raise HTTPException(status_code=404, detail="Parlay not found")

        p = _row_to_dict(parlay)

        if p.get("placed"):
            raise HTTPException(status_code=400, detail="Parlay already placed")
        if p.get("skipped"):
            raise HTTPException(status_code=400, detail="Parlay already skipped")

        conn.execute(
            """
            UPDATE parlays SET skipped = 1, skip_reason = ?
            WHERE parlay_id = ?
            """,
            (body.reason, parlay_id),
        )
        conn.commit()

        return {
            "pick_id": parlay_id,
            "status": "skipped",
            "reason": body.reason,
        }
    finally:
        conn.close()


@router.post("/{parlay_id}/result")
async def record_result(parlay_id: int, body: ResultRequest, request: Request):
    """Record a parlay result (won/lost) and update ladder + shadow portfolio."""
    if body.result not in ("won", "lost"):
        raise HTTPException(status_code=400, detail="Result must be 'won' or 'lost'")

    conn = _get_conn(request)
    config = _get_config(request)
    try:
        parlay = conn.execute(
            "SELECT * FROM parlays WHERE parlay_id = ?", (parlay_id,)
        ).fetchone()

        if not parlay:
            raise HTTPException(status_code=404, detail="Parlay not found")

        p = _row_to_dict(parlay)

        if p.get("result"):
            raise HTTPException(status_code=400, detail=f"Result already recorded: {p['result']}")
        if not p.get("placed"):
            raise HTTPException(status_code=400, detail="Cannot record result for unplaced parlay")

        # Calculate payout
        stake = p.get("actual_stake", 0) or 0
        odds = p.get("fd_parlay_odds") or p["combined_odds"]
        payout = None
        if body.result == "won":
            decimal_odds = american_to_decimal(odds)
            payout = round(stake * decimal_odds, 2)

        # Update parlay result
        conn.execute(
            "UPDATE parlays SET result = ?, payout = ? WHERE parlay_id = ?",
            (body.result, payout, parlay_id),
        )

        # Update individual pick results (both legs same result for a parlay)
        pick_result = body.result
        for pick_id_col in ("leg1_pick_id", "leg2_pick_id"):
            pick_id = p.get(pick_id_col)
            if pick_id:
                conn.execute(
                    "UPDATE picks SET result = ? WHERE pick_id = ?",
                    (pick_result, pick_id),
                )

        # Update shadow flat bets
        from ladderbot.parlay.ladder import ShadowPortfolio
        shadow = ShadowPortfolio(conn)
        for pick_id_col in ("leg1_pick_id", "leg2_pick_id"):
            pick_id = p.get(pick_id_col)
            if pick_id:
                try:
                    shadow.record_result(pick_id, pick_result)
                except ValueError:
                    pass  # No flat bet recorded for this pick

        # Update ladder state
        from ladderbot.parlay.ladder import LadderTracker
        ladder = LadderTracker(conn, config)
        ladder_result = None

        # Auto-start ladder if idle (first bet placed)
        if ladder.status == ladder.IDLE:
            ladder.start_new_attempt()
            ladder.place_bet(parlay_id)

        if ladder.status == ladder.ACTIVE:
            if body.result == "won" and payout:
                ladder_result = ladder.record_win(payout)
            elif body.result == "lost":
                ladder_result = ladder.record_loss()

        conn.commit()

        response = {
            "parlay_id": parlay_id,
            "result": body.result,
            "payout": payout,
            "stake": stake,
        }
        if ladder_result:
            response["ladder"] = ladder_result

        return response
    finally:
        conn.close()
