"""Ladder API routes for LadderBot web dashboard.

Endpoints:
    GET /api/ladder          — Current ladder state
    GET /api/ladder/history  — All ladder attempts with results
"""
from fastapi import APIRouter, Request

from ladderbot.db.database import get_db
from ladderbot.utils.odds import american_to_decimal, ladder_steps_needed


router = APIRouter(prefix="/api/ladder", tags=["ladder"])


def _get_conn(request: Request):
    db_path = getattr(request.app.state, "db_path", None)
    return get_db(db_path)


def _get_config(request: Request) -> dict:
    return getattr(request.app.state, "config", {})


def _row_to_dict(row) -> dict | None:
    if row is None:
        return None
    return dict(row)


@router.get("")
async def get_ladder(request: Request):
    """Get current ladder state with step details."""
    conn = _get_conn(request)
    config = _get_config(request)
    ladder_config = config.get("ladder", {})
    starting_amount = ladder_config.get("starting_amount", 10.0)
    target_amount = ladder_config.get("target_amount", 1000.0)

    try:
        # Get the latest state
        current = conn.execute(
            "SELECT * FROM ladder_state ORDER BY attempt_id DESC, step DESC LIMIT 1"
        ).fetchone()

        if current is None:
            # No ladder started yet
            avg_decimal = american_to_decimal(225)  # default +225
            total_steps = ladder_steps_needed(starting_amount, target_amount, avg_decimal)
            return {
                "active": False,
                "attempt_id": 0,
                "step": 0,
                "bankroll": starting_amount,
                "total_steps": total_steps,
                "starting_amount": starting_amount,
                "target_amount": target_amount,
                "steps": [],
                "stats": {
                    "total_attempts": 0,
                    "total_invested": 0.0,
                    "total_returned": 0.0,
                    "best_step": 0,
                    "best_bankroll": 0.0,
                    "win_rate": 0.0,
                },
            }

        current_dict = _row_to_dict(current)
        attempt_id = current_dict["attempt_id"]

        # Get all steps in current attempt
        steps_rows = conn.execute(
            """
            SELECT ls.*, p.combined_odds, p.result as parlay_result, p.placed_at
            FROM ladder_state ls
            LEFT JOIN parlays p ON ls.parlay_id = p.parlay_id
            WHERE ls.attempt_id = ?
            ORDER BY ls.step ASC
            """,
            (attempt_id,),
        ).fetchall()

        steps = [_row_to_dict(r) for r in steps_rows]

        # Calculate total steps needed based on average odds
        avg_odds_row = conn.execute(
            "SELECT AVG(combined_odds) as avg_odds FROM parlays WHERE placed = 1"
        ).fetchone()

        if avg_odds_row and avg_odds_row["avg_odds"]:
            avg_decimal = american_to_decimal(int(avg_odds_row["avg_odds"]))
        else:
            avg_decimal = american_to_decimal(225)

        total_steps = ladder_steps_needed(starting_amount, target_amount, avg_decimal)

        # Compute stats across all attempts
        all_attempts = conn.execute(
            """
            SELECT attempt_id, MAX(step) as max_step, MAX(bankroll) as max_bankroll,
                   result
            FROM ladder_state
            GROUP BY attempt_id
            ORDER BY attempt_id
            """
        ).fetchall()

        total_attempts = len(all_attempts)
        total_invested = total_attempts * starting_amount
        total_returned_row = conn.execute(
            """
            SELECT COALESCE(SUM(payout), 0) as total
            FROM parlays WHERE placed = 1 AND result = 'won'
            """
        ).fetchone()
        total_returned = total_returned_row["total"] if total_returned_row else 0.0

        best_step = max((r["max_step"] for r in all_attempts), default=0)
        best_bankroll = max((r["max_bankroll"] for r in all_attempts), default=0.0)

        # Win rate across all placed parlays in ladder
        placed_count = conn.execute(
            "SELECT COUNT(*) as cnt FROM parlays WHERE placed = 1"
        ).fetchone()["cnt"]
        won_count = conn.execute(
            "SELECT COUNT(*) as cnt FROM parlays WHERE placed = 1 AND result = 'won'"
        ).fetchone()["cnt"]
        win_rate = won_count / placed_count if placed_count > 0 else 0.0

        is_active = current_dict.get("result") is None

        return {
            "active": is_active,
            "attempt_id": attempt_id,
            "step": current_dict["step"],
            "bankroll": current_dict["bankroll"],
            "total_steps": total_steps,
            "starting_amount": starting_amount,
            "target_amount": target_amount,
            "steps": steps,
            "stats": {
                "total_attempts": total_attempts,
                "total_invested": total_invested,
                "total_returned": total_returned,
                "best_step": best_step,
                "best_bankroll": best_bankroll,
                "win_rate": round(win_rate, 3),
            },
        }
    finally:
        conn.close()


@router.get("/history")
async def get_ladder_history(request: Request):
    """Get all ladder attempts with their step details."""
    conn = _get_conn(request)
    config = _get_config(request)
    starting_amount = config.get("ladder", {}).get("starting_amount", 10.0)

    try:
        # Get distinct attempts
        attempts_rows = conn.execute(
            """
            SELECT attempt_id, MIN(timestamp) as started_at,
                   MAX(step) as max_step, MAX(bankroll) as peak_bankroll
            FROM ladder_state
            GROUP BY attempt_id
            ORDER BY attempt_id DESC
            """
        ).fetchall()

        attempts = []
        for att in attempts_rows:
            a = _row_to_dict(att)
            # Get final result for this attempt
            final_step = conn.execute(
                """
                SELECT * FROM ladder_state
                WHERE attempt_id = ?
                ORDER BY step DESC LIMIT 1
                """,
                (a["attempt_id"],),
            ).fetchone()

            final = _row_to_dict(final_step)

            # Get all steps with parlay details
            steps_rows = conn.execute(
                """
                SELECT ls.*, p.combined_odds, p.result as parlay_result
                FROM ladder_state ls
                LEFT JOIN parlays p ON ls.parlay_id = p.parlay_id
                WHERE ls.attempt_id = ?
                ORDER BY ls.step ASC
                """,
                (a["attempt_id"],),
            ).fetchall()

            attempts.append({
                "attempt_id": a["attempt_id"],
                "started_at": a["started_at"],
                "max_step": a["max_step"],
                "peak_bankroll": a["peak_bankroll"],
                "result": final.get("result"),
                "steps": [_row_to_dict(s) for s in steps_rows],
            })

        return {
            "starting_amount": starting_amount,
            "attempts": attempts,
        }
    finally:
        conn.close()
