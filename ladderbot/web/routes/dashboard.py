"""Performance and dashboard API routes for LadderBot web dashboard.

Endpoints:
    GET /api/performance              — Portfolio stats
    GET /api/performance/chart/{m}    — Chart data (pl_over_time, calibration, clv_scatter)
    GET /api/bets                     — Filterable bet history
    GET /api/health                   — System health
    GET /events                       — SSE stream for real-time updates
"""
import asyncio
import json
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse

from ladderbot.db.database import get_db


router = APIRouter(tags=["dashboard"])


def _get_conn(request: Request):
    db_path = getattr(request.app.state, "db_path", None)
    return get_db(db_path)


def _row_to_dict(row) -> dict | None:
    if row is None:
        return None
    return dict(row)


# -- Performance ---------------------------------------------------------------


@router.get("/api/performance")
async def get_performance(request: Request):
    """Get shadow flat-bet portfolio stats, ladder P/L, and model metrics."""
    conn = _get_conn(request)
    try:
        # Shadow flat-bet portfolio
        flat_stats = conn.execute(
            """
            SELECT
                COUNT(*) as total_bets,
                SUM(CASE WHEN result = 'won' THEN 1 ELSE 0 END) as wins,
                SUM(CASE WHEN result = 'lost' THEN 1 ELSE 0 END) as losses,
                SUM(CASE WHEN result = 'push' THEN 1 ELSE 0 END) as pushes,
                COALESCE(SUM(profit_loss), 0) as total_profit,
                COALESCE(SUM(amount), 0) as total_wagered
            FROM flat_bets
            WHERE result IS NOT NULL
            """
        ).fetchone()
        fs = _row_to_dict(flat_stats) or {}

        total_bets = fs.get("total_bets", 0)
        wins = fs.get("wins", 0)
        losses = fs.get("losses", 0)
        total_wagered = fs.get("total_wagered", 0)
        total_profit = fs.get("total_profit", 0)
        roi = (total_profit / total_wagered * 100) if total_wagered > 0 else 0.0
        win_rate = (wins / total_bets * 100) if total_bets > 0 else 0.0

        # By sport
        sport_stats = conn.execute(
            """
            SELECT g.sport,
                COUNT(*) as bets,
                SUM(CASE WHEN fb.result = 'won' THEN 1 ELSE 0 END) as wins,
                SUM(CASE WHEN fb.result = 'lost' THEN 1 ELSE 0 END) as losses
            FROM flat_bets fb
            JOIN picks pk ON fb.pick_id = pk.pick_id
            JOIN games g ON pk.game_id = g.game_id
            WHERE fb.result IS NOT NULL
            GROUP BY g.sport
            """
        ).fetchall()
        by_sport = {r["sport"]: {"bets": r["bets"], "wins": r["wins"], "losses": r["losses"]} for r in sport_stats}

        # Ladder P/L
        ladder_stats = conn.execute(
            """
            SELECT
                COUNT(DISTINCT attempt_id) as attempts,
                COALESCE(SUM(CASE WHEN placed = 1 THEN actual_stake ELSE 0 END), 0) as total_wagered,
                COALESCE(SUM(CASE WHEN placed = 1 AND result = 'won' THEN payout ELSE 0 END), 0) as total_returned
            FROM parlays
            """
        ).fetchone()
        ls = _row_to_dict(ladder_stats) or {}

        ladder_wagered = ls.get("total_wagered", 0)
        ladder_returned = ls.get("total_returned", 0)

        # CLV stats
        clv_stats = conn.execute(
            """
            SELECT
                AVG(clv) as avg_clv,
                COUNT(*) as clv_count
            FROM picks
            WHERE clv IS NOT NULL
            """
        ).fetchone()
        cs = _row_to_dict(clv_stats) or {}

        # Model calibration (Brier scores from predictions vs results)
        brier_stats = conn.execute(
            """
            SELECT g.sport,
                AVG((mp.model_prob - CASE WHEN pk.result = 'won' THEN 1.0 ELSE 0.0 END)
                    * (mp.model_prob - CASE WHEN pk.result = 'won' THEN 1.0 ELSE 0.0 END)) as brier
            FROM model_predictions mp
            JOIN picks pk ON mp.game_id = pk.game_id AND mp.market = pk.market AND mp.outcome = pk.outcome
            JOIN games g ON mp.game_id = g.game_id
            WHERE pk.result IS NOT NULL
            GROUP BY g.sport
            """
        ).fetchall()
        brier_by_sport = {r["sport"]: round(r["brier"], 4) for r in brier_stats}

        return {
            "shadow_portfolio": {
                "total_bets": total_bets,
                "wins": wins,
                "losses": losses,
                "win_rate": round(win_rate, 1),
                "total_profit": round(total_profit, 2),
                "total_wagered": round(total_wagered, 2),
                "roi": round(roi, 1),
                "by_sport": by_sport,
            },
            "ladder_pl": {
                "total_wagered": round(ladder_wagered, 2),
                "total_returned": round(ladder_returned, 2),
                "net": round(ladder_returned - ladder_wagered, 2),
            },
            "clv": {
                "average": round(cs.get("avg_clv", 0) or 0, 4),
                "count": cs.get("clv_count", 0),
            },
            "calibration": brier_by_sport,
        }
    finally:
        conn.close()


# -- Chart data ----------------------------------------------------------------


@router.get("/api/performance/chart/{metric}")
async def get_chart_data(metric: str, request: Request):
    """Get chart data for a specific metric.

    Supported metrics:
        - pl_over_time: cumulative P/L line chart data
        - calibration: predicted vs actual probability bins
        - clv_scatter: CLV per bet over time
    """
    conn = _get_conn(request)
    try:
        if metric == "pl_over_time":
            rows = conn.execute(
                """
                SELECT fb.timestamp, fb.profit_loss, fb.result
                FROM flat_bets fb
                WHERE fb.result IS NOT NULL
                ORDER BY fb.timestamp ASC
                """
            ).fetchall()

            cumulative = 0.0
            labels = []
            data = []
            for r in rows:
                cumulative += r["profit_loss"] or 0
                labels.append(r["timestamp"])
                data.append(round(cumulative, 2))

            return {
                "metric": "pl_over_time",
                "labels": labels,
                "datasets": [{
                    "label": "Cumulative P/L ($)",
                    "data": data,
                }],
            }

        elif metric == "calibration":
            # Bin predictions into 5% intervals
            rows = conn.execute(
                """
                SELECT mp.model_prob,
                    CASE WHEN pk.result = 'won' THEN 1.0 ELSE 0.0 END as actual
                FROM model_predictions mp
                JOIN picks pk ON mp.game_id = pk.game_id
                    AND mp.market = pk.market AND mp.outcome = pk.outcome
                WHERE pk.result IS NOT NULL
                """
            ).fetchall()

            bins = {}
            for r in rows:
                bucket = round(r["model_prob"] * 20) / 20  # 5% bins
                bucket = round(bucket, 2)
                if bucket not in bins:
                    bins[bucket] = {"total": 0, "wins": 0}
                bins[bucket]["total"] += 1
                bins[bucket]["wins"] += r["actual"]

            sorted_bins = sorted(bins.keys())
            labels = [f"{int(b*100)}%" for b in sorted_bins]
            predicted = [b * 100 for b in sorted_bins]
            actual = [
                round(bins[b]["wins"] / bins[b]["total"] * 100, 1)
                if bins[b]["total"] > 0 else 0
                for b in sorted_bins
            ]

            return {
                "metric": "calibration",
                "labels": labels,
                "datasets": [
                    {"label": "Predicted %", "data": predicted},
                    {"label": "Actual %", "data": actual},
                ],
            }

        elif metric == "clv_scatter":
            rows = conn.execute(
                """
                SELECT pk.pick_id, pk.clv, g.game_date, g.sport
                FROM picks pk
                JOIN games g ON pk.game_id = g.game_id
                WHERE pk.clv IS NOT NULL
                ORDER BY g.game_date ASC
                """
            ).fetchall()

            labels = [r["game_date"] for r in rows]
            data = [round(r["clv"] * 100, 2) for r in rows]
            sports = [r["sport"] for r in rows]

            return {
                "metric": "clv_scatter",
                "labels": labels,
                "datasets": [{
                    "label": "CLV (%)",
                    "data": data,
                }],
                "sports": sports,
            }

        else:
            return {"error": f"Unknown metric: {metric}"}
    finally:
        conn.close()


# -- Bet history ---------------------------------------------------------------


@router.get("/api/bets")
async def get_bets(
    request: Request,
    sport: Optional[str] = Query(None),
    result: Optional[str] = Query(None),
    placed: Optional[str] = Query(None),
):
    """Get filterable bet history.

    Query params:
        sport: 'nba' or 'nhl'
        result: 'won', 'lost', 'push', 'pending'
        placed: 'true' or 'false'
    """
    conn = _get_conn(request)
    try:
        query = """
            SELECT p.parlay_id, p.combined_odds, p.combined_edge, p.result,
                   p.payout, p.placed, p.skipped, p.actual_stake,
                   p.created_at, p.fd_parlay_odds,
                   pk1.outcome as leg1_outcome, pk1.market as leg1_market,
                   pk1.odds_at_pick as leg1_odds,
                   g1.sport as leg1_sport, g1.home_team as leg1_home,
                   g1.away_team as leg1_away, g1.game_date as leg1_date,
                   pk2.outcome as leg2_outcome, pk2.market as leg2_market,
                   pk2.odds_at_pick as leg2_odds,
                   g2.sport as leg2_sport, g2.home_team as leg2_home,
                   g2.away_team as leg2_away, g2.game_date as leg2_date
            FROM parlays p
            LEFT JOIN picks pk1 ON p.leg1_pick_id = pk1.pick_id
            LEFT JOIN games g1 ON pk1.game_id = g1.game_id
            LEFT JOIN picks pk2 ON p.leg2_pick_id = pk2.pick_id
            LEFT JOIN games g2 ON pk2.game_id = g2.game_id
            WHERE 1=1
        """
        params = []

        if sport:
            query += " AND (g1.sport = ? OR g2.sport = ?)"
            params.extend([sport, sport])

        if result:
            if result == "pending":
                query += " AND p.result IS NULL"
            else:
                query += " AND p.result = ?"
                params.append(result)

        if placed is not None:
            if placed.lower() == "true":
                query += " AND p.placed = 1"
            elif placed.lower() == "false":
                query += " AND p.placed = 0"

        query += " ORDER BY p.created_at DESC"

        rows = conn.execute(query, params).fetchall()

        bets = []
        for r in rows:
            d = _row_to_dict(r)
            # Build display description
            leg1_desc = _format_leg(d, "leg1")
            leg2_desc = _format_leg(d, "leg2")

            bets.append({
                "parlay_id": d["parlay_id"],
                "date": d.get("leg1_date") or d.get("created_at", "")[:10],
                "description": f"{leg1_desc} + {leg2_desc}",
                "odds": d.get("fd_parlay_odds") or d["combined_odds"],
                "result": d["result"] or "pending",
                "placed": bool(d["placed"]),
                "skipped": bool(d["skipped"]),
                "stake": d["actual_stake"],
                "payout": d["payout"],
                "profit_loss": _calc_pl(d),
                "sport": d.get("leg1_sport", ""),
            })

        return {"bets": bets}
    finally:
        conn.close()


def _format_leg(d: dict, prefix: str) -> str:
    """Format a leg description from row data."""
    outcome = d.get(f"{prefix}_outcome", "")
    market = d.get(f"{prefix}_market", "")
    home = d.get(f"{prefix}_home", "")
    away = d.get(f"{prefix}_away", "")
    odds = d.get(f"{prefix}_odds", "")

    if market == "h2h":
        return f"{outcome} ML ({odds:+d})" if odds else f"{outcome} ML"
    elif market == "totals":
        return f"{home}/{away} {outcome} ({odds:+d})" if odds else f"{outcome}"
    else:
        return f"{outcome} ({odds:+d})" if odds else outcome


def _calc_pl(d: dict) -> float | None:
    """Calculate profit/loss for a placed bet."""
    if not d.get("placed") or d.get("result") is None:
        return None
    if d["result"] == "won":
        return round((d.get("payout", 0) or 0) - (d.get("actual_stake", 0) or 0), 2)
    elif d["result"] == "lost":
        return -(d.get("actual_stake", 0) or 0)
    return 0.0


# -- Health --------------------------------------------------------------------


@router.get("/api/health")
async def get_health(request: Request):
    """System health check — DB status, last data refresh, model staleness."""
    conn = _get_conn(request)
    try:
        # Check DB connectivity
        db_ok = True
        try:
            conn.execute("SELECT 1")
        except Exception:
            db_ok = False

        # Last odds refresh
        last_odds = conn.execute(
            "SELECT MAX(timestamp) as ts FROM odds_snapshots"
        ).fetchone()

        # Last prediction
        last_pred = conn.execute(
            "SELECT MAX(timestamp) as ts FROM model_predictions"
        ).fetchone()

        # Last parlay created
        last_parlay = conn.execute(
            "SELECT MAX(created_at) as ts FROM parlays"
        ).fetchone()

        # Game counts
        game_counts = conn.execute(
            """
            SELECT sport, COUNT(*) as cnt
            FROM games
            WHERE game_date = date('now')
            GROUP BY sport
            """
        ).fetchall()

        return {
            "status": "healthy" if db_ok else "degraded",
            "database": "connected" if db_ok else "error",
            "last_odds_refresh": _row_to_dict(last_odds).get("ts") if last_odds else None,
            "last_prediction": _row_to_dict(last_pred).get("ts") if last_pred else None,
            "last_parlay": _row_to_dict(last_parlay).get("ts") if last_parlay else None,
            "today_games": {r["sport"]: r["cnt"] for r in game_counts},
            "timestamp": datetime.now().isoformat(),
        }
    finally:
        conn.close()


# -- SSE stream ----------------------------------------------------------------


@router.get("/events")
async def sse_stream(request: Request):
    """Server-Sent Events stream for real-time dashboard updates.

    Sends events:
        - heartbeat: every 15 seconds
        - picks_update: when new picks arrive
        - result_update: when a game result comes in
        - ladder_update: when ladder state changes
    """
    async def event_generator():
        last_parlay_count = 0
        last_result_count = 0

        while True:
            # Check if client disconnected
            if await request.is_disconnected():
                break

            try:
                conn = _get_conn(request)

                # Check for new parlays
                row = conn.execute(
                    "SELECT COUNT(*) as cnt FROM parlays WHERE date(created_at) = date('now')"
                ).fetchone()
                current_parlay_count = row["cnt"] if row else 0

                if current_parlay_count > last_parlay_count and last_parlay_count > 0:
                    yield f"event: picks_update\ndata: {json.dumps({'count': current_parlay_count})}\n\n"
                last_parlay_count = current_parlay_count

                # Check for new results
                result_row = conn.execute(
                    """
                    SELECT COUNT(*) as cnt FROM parlays
                    WHERE result IS NOT NULL AND date(created_at) = date('now')
                    """
                ).fetchone()
                current_result_count = result_row["cnt"] if result_row else 0

                if current_result_count > last_result_count and last_result_count > 0:
                    yield f"event: result_update\ndata: {json.dumps({'count': current_result_count})}\n\n"
                last_result_count = current_result_count

                conn.close()
            except Exception:
                pass

            # Heartbeat
            yield f"event: heartbeat\ndata: {json.dumps({'time': datetime.now().isoformat()})}\n\n"

            await asyncio.sleep(15)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
