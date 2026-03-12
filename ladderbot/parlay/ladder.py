"""Ladder state machine and shadow flat-bet portfolio for LadderBot.

LadderTracker manages the ladder progression from $10 to $1,000:
    IDLE -> ACTIVE -> WON -> next step (ACTIVE) or COMPLETE
                      LOST -> RESET (back to IDLE, new attempt)

ShadowPortfolio tracks every parlay pick as a flat $10 bet to isolate
model quality from ladder variance.
"""
import math
import sqlite3
from typing import Optional

from ladderbot.utils.odds import american_to_decimal, ladder_steps_needed


class LadderTracker:
    """Manages ladder state transitions and persistence.

    Attributes:
        db: SQLite connection.
        config: Configuration dict with ladder settings.
    """

    # Ladder statuses
    IDLE = "IDLE"
    ACTIVE = "ACTIVE"
    COMPLETE = "COMPLETE"

    def __init__(self, db: sqlite3.Connection, config: dict):
        self.db = db
        ladder_cfg = config.get("ladder", {})
        self._starting_amount = ladder_cfg.get("starting_amount", 10.0)
        self._target_amount = ladder_cfg.get("target_amount", 1000.0)
        self._max_attempts = ladder_cfg.get("max_attempts", 50)

    @property
    def status(self) -> str:
        """Current ladder status: IDLE, ACTIVE, or COMPLETE."""
        row = self._latest_state()
        if row is None:
            return self.IDLE
        if row["result"] == "lost":
            return self.IDLE
        if row["bankroll"] >= self._target_amount:
            return self.COMPLETE
        if row["result"] == "won" or row["result"] is None:
            return self.ACTIVE
        return self.IDLE

    @property
    def current_step(self) -> int:
        """Current step number (0 if idle)."""
        row = self._latest_state()
        if row is None:
            return 0
        if row["result"] == "lost":
            return 0
        return row["step"]

    @property
    def current_bankroll(self) -> float:
        """Current bankroll amount."""
        row = self._latest_state()
        if row is None:
            return self._starting_amount
        if row["result"] == "lost":
            return self._starting_amount
        return row["bankroll"]

    @property
    def total_steps(self) -> int:
        """Total steps needed based on average parlay odds (default 3.25)."""
        return ladder_steps_needed(
            self._starting_amount, self._target_amount, 3.25
        )

    @property
    def attempt_number(self) -> int:
        """Current attempt number (1-based)."""
        row = self.db.execute(
            "SELECT MAX(attempt_id) as max_id FROM ladder_state"
        ).fetchone()
        if row is None or row["max_id"] is None:
            return 0
        # If latest state is a loss, next attempt will be max_id + 1,
        # but we report the count of attempts started
        return row["max_id"]

    def start_new_attempt(self) -> dict:
        """Start a new ladder attempt at step 1 with starting bankroll.

        Returns:
            Dict with attempt_id, step, bankroll.
        """
        new_attempt_id = self.attempt_number + 1
        self.db.execute(
            """
            INSERT INTO ladder_state (attempt_id, step, bankroll, parlay_id, result)
            VALUES (?, ?, ?, ?, ?)
            """,
            (new_attempt_id, 1, self._starting_amount, None, None),
        )
        self.db.commit()
        return {
            "attempt_id": new_attempt_id,
            "step": 1,
            "bankroll": self._starting_amount,
        }

    def place_bet(self, parlay_id: int) -> dict:
        """Record that a bet has been placed on the current step.

        Args:
            parlay_id: The parlay being bet.

        Returns:
            Dict with current state.
        """
        row = self._latest_state()
        if row is None:
            raise ValueError("No active ladder. Call start_new_attempt first.")

        attempt_id = row["attempt_id"]
        step = row["step"]
        bankroll = row["bankroll"]

        # Update the current state row with the parlay_id
        self.db.execute(
            """
            UPDATE ladder_state
            SET parlay_id = ?
            WHERE attempt_id = ? AND step = ? AND parlay_id IS NULL
            """,
            (parlay_id, attempt_id, step),
        )
        self.db.commit()

        return {
            "attempt_id": attempt_id,
            "step": step,
            "bankroll": bankroll,
            "parlay_id": parlay_id,
        }

    def record_win(self, payout: float) -> dict:
        """Record a win and advance the ladder.

        Args:
            payout: Total payout (stake + profit).

        Returns:
            Dict with new state including whether ladder is complete.
        """
        row = self._latest_state()
        if row is None:
            raise ValueError("No active ladder.")

        attempt_id = row["attempt_id"]
        current_step = row["step"]
        new_bankroll = payout

        # Mark current step as won and update bankroll to payout
        self.db.execute(
            """
            UPDATE ladder_state SET result = 'won', bankroll = ?
            WHERE attempt_id = ? AND step = ?
            """,
            (new_bankroll, attempt_id, current_step),
        )

        complete = new_bankroll >= self._target_amount

        if not complete:
            # Insert next step
            next_step = current_step + 1
            self.db.execute(
                """
                INSERT INTO ladder_state (attempt_id, step, bankroll, parlay_id, result)
                VALUES (?, ?, ?, ?, ?)
                """,
                (attempt_id, next_step, new_bankroll, None, None),
            )

        self.db.commit()

        return {
            "attempt_id": attempt_id,
            "step": current_step + 1 if not complete else current_step,
            "bankroll": new_bankroll,
            "complete": complete,
        }

    def record_loss(self) -> dict:
        """Record a loss and reset the ladder.

        Returns:
            Dict with loss details.
        """
        row = self._latest_state()
        if row is None:
            raise ValueError("No active ladder.")

        attempt_id = row["attempt_id"]
        step = row["step"]

        # Mark current step as lost
        self.db.execute(
            """
            UPDATE ladder_state SET result = 'lost'
            WHERE attempt_id = ? AND step = ?
            """,
            (attempt_id, step),
        )
        self.db.commit()

        return {
            "attempt_id": attempt_id,
            "step_reached": step,
            "bankroll_lost": row["bankroll"],
        }

    def get_ladder_display(self) -> dict:
        """Get full ladder display data for CLI/web dashboard.

        Returns:
            Dict with current state, history summary, and stats.
        """
        return {
            "status": self.status,
            "current_step": self.current_step,
            "current_bankroll": self.current_bankroll,
            "total_steps": self.total_steps,
            "attempt_number": self.attempt_number,
            "starting_amount": self._starting_amount,
            "target_amount": self._target_amount,
        }

    def get_history(self) -> list[dict]:
        """Get history of all ladder attempts.

        Returns:
            List of dicts, one per attempt, with steps and results.
        """
        rows = self.db.execute(
            """
            SELECT attempt_id, step, bankroll, result, timestamp
            FROM ladder_state
            ORDER BY attempt_id, step
            """
        ).fetchall()

        attempts: dict[int, list] = {}
        for row in rows:
            aid = row["attempt_id"]
            if aid not in attempts:
                attempts[aid] = []
            attempts[aid].append({
                "step": row["step"],
                "bankroll": row["bankroll"],
                "result": row["result"],
                "timestamp": row["timestamp"],
            })

        return [
            {"attempt_id": aid, "steps": steps}
            for aid, steps in sorted(attempts.items())
        ]

    def _latest_state(self) -> Optional[sqlite3.Row]:
        """Get the most recent ladder state row."""
        return self.db.execute(
            "SELECT * FROM ladder_state ORDER BY attempt_id DESC, step DESC LIMIT 1"
        ).fetchone()


class ShadowPortfolio:
    """Tracks flat-bet performance independent of ladder variance.

    Every parlay pick is recorded as a flat $10 bet for model evaluation.
    """

    FLAT_AMOUNT = 10.0

    def __init__(self, db: sqlite3.Connection):
        self.db = db

    def record_bet(self, pick_id: int, odds: int) -> int:
        """Record a shadow flat bet.

        Args:
            pick_id: The pick being tracked.
            odds: American odds at time of pick.

        Returns:
            The flat_bet row id.
        """
        cursor = self.db.execute(
            """
            INSERT INTO flat_bets (pick_id, amount, odds)
            VALUES (?, ?, ?)
            """,
            (pick_id, self.FLAT_AMOUNT, odds),
        )
        self.db.commit()
        return cursor.lastrowid

    def record_result(self, pick_id: int, result: str) -> float:
        """Record the result of a shadow bet.

        Args:
            pick_id: The pick whose result is being recorded.
            result: 'won' or 'lost'.

        Returns:
            The profit/loss amount.
        """
        row = self.db.execute(
            "SELECT * FROM flat_bets WHERE pick_id = ? ORDER BY id DESC LIMIT 1",
            (pick_id,),
        ).fetchone()

        if row is None:
            raise ValueError(f"No flat bet found for pick_id={pick_id}")

        if result == "won":
            decimal_odds = american_to_decimal(row["odds"])
            profit = self.FLAT_AMOUNT * (decimal_odds - 1)
        else:
            profit = -self.FLAT_AMOUNT

        self.db.execute(
            """
            UPDATE flat_bets SET result = ?, profit_loss = ?
            WHERE id = ?
            """,
            (result, profit, row["id"]),
        )
        self.db.commit()
        return profit

    def get_stats(self) -> dict:
        """Get shadow portfolio statistics.

        Returns:
            Dict with record, profit, roi, by_sport breakdown.
        """
        rows = self.db.execute(
            """
            SELECT fb.result, fb.profit_loss, fb.odds, p.game_id
            FROM flat_bets fb
            JOIN picks p ON fb.pick_id = p.pick_id
            WHERE fb.result IS NOT NULL
            """
        ).fetchall()

        if not rows:
            return {
                "wins": 0,
                "losses": 0,
                "total_bets": 0,
                "profit": 0.0,
                "roi": 0.0,
                "by_sport": {},
            }

        wins = sum(1 for r in rows if r["result"] == "won")
        losses = sum(1 for r in rows if r["result"] == "lost")
        total_profit = sum(r["profit_loss"] for r in rows if r["profit_loss"] is not None)
        total_wagered = len(rows) * self.FLAT_AMOUNT

        # By sport breakdown (infer from game_id prefix)
        by_sport: dict[str, dict] = {}
        for r in rows:
            game_id = r["game_id"] or ""
            sport = game_id.split("_")[0] if "_" in game_id else "unknown"
            if sport not in by_sport:
                by_sport[sport] = {"wins": 0, "losses": 0, "profit": 0.0}
            if r["result"] == "won":
                by_sport[sport]["wins"] += 1
            else:
                by_sport[sport]["losses"] += 1
            if r["profit_loss"] is not None:
                by_sport[sport]["profit"] += r["profit_loss"]

        return {
            "wins": wins,
            "losses": losses,
            "total_bets": wins + losses,
            "profit": total_profit,
            "roi": (total_profit / total_wagered * 100) if total_wagered > 0 else 0.0,
            "by_sport": by_sport,
        }
