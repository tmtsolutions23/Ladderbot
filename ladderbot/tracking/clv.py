"""Closing Line Value (CLV) tracker for LadderBot.

CLV is the single best predictor of long-term profitability. If you
consistently bet lines that move in your favor before close, you have
real edge.

CLV = closing_implied_prob - pick_implied_prob
  Positive CLV = closing line moved toward your bet (good — you beat the close)
  Negative CLV = closing line moved away from your bet (bad)
"""
import sqlite3
from typing import Optional

from ladderbot.utils.odds import implied_probability


class CLVTracker:
    """Tracks and computes Closing Line Value for picks."""

    def __init__(self, db: sqlite3.Connection):
        self.db = db

    def record_pick(
        self,
        pick_id: int,
        game_id: str,
        market: str,
        odds_at_pick: int,
    ) -> None:
        """Record odds at time of pick for CLV computation.

        This updates the picks table row (already inserted by the pipeline)
        to ensure odds_at_pick is set. If the pick was inserted with correct
        odds, this is a no-op confirmation.

        Args:
            pick_id: ID of the pick in the picks table.
            game_id: Game identifier.
            market: Market type (h2h, totals).
            odds_at_pick: American odds when pick was made.
        """
        self.db.execute(
            """
            UPDATE picks SET odds_at_pick = ?
            WHERE pick_id = ?
            """,
            (odds_at_pick, pick_id),
        )
        self.db.commit()

    def record_closing_odds(
        self,
        game_id: str,
        market: str,
        closing_odds: int,
    ) -> int:
        """Record closing odds for all picks on a game/market.

        Args:
            game_id: Game identifier.
            market: Market type (h2h, totals).
            closing_odds: American odds at close.

        Returns:
            Number of picks updated.
        """
        cursor = self.db.execute(
            """
            UPDATE picks SET closing_odds = ?
            WHERE game_id = ? AND market = ?
            """,
            (closing_odds, game_id, market),
        )
        self.db.commit()
        return cursor.rowcount

    def compute_clv(self, pick_id: int) -> Optional[float]:
        """Compute CLV for a single pick.

        CLV = closing_implied_prob - pick_implied_prob
        Positive = closing line moved toward your bet (good).

        Args:
            pick_id: ID of the pick.

        Returns:
            CLV as a float, or None if closing odds not yet recorded.
        """
        row = self.db.execute(
            "SELECT odds_at_pick, closing_odds FROM picks WHERE pick_id = ?",
            (pick_id,),
        ).fetchone()

        if row is None:
            return None
        if row["closing_odds"] is None:
            return None

        pick_implied = implied_probability(row["odds_at_pick"])
        closing_implied = implied_probability(row["closing_odds"])
        clv = closing_implied - pick_implied

        # Store computed CLV
        self.db.execute(
            "UPDATE picks SET clv = ? WHERE pick_id = ?",
            (clv, pick_id),
        )
        self.db.commit()

        return clv

    def get_rolling_clv(self, n: int = 50) -> Optional[float]:
        """Get rolling average CLV over the last n picks with CLV data.

        Args:
            n: Number of recent picks to average.

        Returns:
            Average CLV, or None if no picks have CLV data.
        """
        rows = self.db.execute(
            """
            SELECT clv FROM picks
            WHERE clv IS NOT NULL
            ORDER BY pick_id DESC
            LIMIT ?
            """,
            (n,),
        ).fetchall()

        if not rows:
            return None

        return sum(r["clv"] for r in rows) / len(rows)

    def get_clv_trend(self) -> list[dict]:
        """Get CLV for all picks that have CLV data, in chronological order.

        Returns:
            List of dicts with pick_id, game_id, odds_at_pick,
            closing_odds, and clv.
        """
        rows = self.db.execute(
            """
            SELECT pick_id, game_id, market, odds_at_pick, closing_odds, clv
            FROM picks
            WHERE clv IS NOT NULL
            ORDER BY pick_id ASC
            """
        ).fetchall()

        return [
            {
                "pick_id": r["pick_id"],
                "game_id": r["game_id"],
                "market": r["market"],
                "odds_at_pick": r["odds_at_pick"],
                "closing_odds": r["closing_odds"],
                "clv": r["clv"],
            }
            for r in rows
        ]
