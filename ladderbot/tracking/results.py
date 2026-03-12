"""Results resolver for LadderBot.

Checks game scores and resolves picks as won/lost/push.
Handles moneyline (h2h) and totals (over/under) outcomes.
"""
import sqlite3
from typing import Optional

from ladderbot.db.database import insert_game


class ResultsResolver:
    """Resolves pick outcomes based on final game scores."""

    def __init__(self, db: sqlite3.Connection, config: dict | None = None):
        self.db = db
        self.config = config or {}

    def check_game_results(self, game_date: str) -> list[dict]:
        """Fetch final scores for all games on a date.

        Reads from the games table. In production, an upstream data layer
        would update game scores; this method returns what is in the DB.

        Args:
            game_date: ISO date string (YYYY-MM-DD).

        Returns:
            List of game result dicts with game_id, home_team, away_team,
            home_score, away_score, sport, status.
        """
        rows = self.db.execute(
            """
            SELECT game_id, sport, home_team, away_team,
                   home_score, away_score, status
            FROM games
            WHERE game_date = ?
            """,
            (game_date,),
        ).fetchall()

        return [
            {
                "game_id": r["game_id"],
                "sport": r["sport"],
                "home_team": r["home_team"],
                "away_team": r["away_team"],
                "home_score": r["home_score"],
                "away_score": r["away_score"],
                "status": r["status"],
            }
            for r in rows
        ]

    def resolve_picks(self, game_results: list[dict]) -> list[dict]:
        """Resolve all pending picks for the given game results.

        Args:
            game_results: List of game result dicts (from check_game_results).

        Returns:
            List of resolved pick dicts with pick_id, result, game_id.
        """
        resolved = []

        for result in game_results:
            if result["status"] != "final":
                continue
            if result["home_score"] is None or result["away_score"] is None:
                continue

            # Find pending picks for this game
            picks = self.db.execute(
                """
                SELECT pick_id, market, outcome, odds_at_pick
                FROM picks
                WHERE game_id = ? AND result IS NULL
                """,
                (result["game_id"],),
            ).fetchall()

            for pick in picks:
                won = self._evaluate_pick(
                    {
                        "market": pick["market"],
                        "outcome": pick["outcome"],
                        "odds_at_pick": pick["odds_at_pick"],
                    },
                    result,
                )

                if won is None:
                    pick_result = "push"
                elif won:
                    pick_result = "won"
                else:
                    pick_result = "lost"

                self.db.execute(
                    "UPDATE picks SET result = ? WHERE pick_id = ?",
                    (pick_result, pick["pick_id"]),
                )

                resolved.append({
                    "pick_id": pick["pick_id"],
                    "game_id": result["game_id"],
                    "result": pick_result,
                    "market": pick["market"],
                    "outcome": pick["outcome"],
                })

        self.db.commit()
        return resolved

    def _evaluate_pick(
        self,
        pick: dict,
        result: dict,
    ) -> Optional[bool]:
        """Evaluate whether a single pick won or lost.

        Args:
            pick: Dict with market, outcome, odds_at_pick.
            result: Dict with home_team, away_team, home_score, away_score.

        Returns:
            True if won, False if lost, None if push.
        """
        market = pick["market"]
        outcome = pick["outcome"]
        home_score = result["home_score"]
        away_score = result["away_score"]
        home_team = result["home_team"]
        away_team = result["away_team"]

        if market == "h2h":
            # Moneyline: outcome is the team abbreviation
            if outcome == home_team:
                return home_score > away_score
            elif outcome == away_team:
                return away_score > home_score
            else:
                # Unknown team in outcome
                return False

        elif market == "totals":
            # Totals: outcome is "Over" or "Under"
            # Need point (the total line) from odds_snapshots or pick context
            # For now, we look up the point from odds_snapshots
            total = home_score + away_score

            point_row = self.db.execute(
                """
                SELECT point FROM odds_snapshots
                WHERE game_id = ? AND market = 'totals'
                ORDER BY timestamp DESC LIMIT 1
                """,
                (result["game_id"],),
            ).fetchone()

            if point_row is None or point_row["point"] is None:
                # Cannot resolve without the line
                return None

            line = point_row["point"]

            if total == line:
                return None  # Push

            if outcome.lower() == "over":
                return total > line
            elif outcome.lower() == "under":
                return total < line

        return None
