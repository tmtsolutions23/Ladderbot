"""Discord webhook client for LadderBot.

Sends alerts via Discord webhooks with retry logic and fallback to logging.
"""
import logging
import time
from typing import Optional

import httpx

from ladderbot.alerts.formatter import (
    format_pick_embed,
    format_result_embed,
    format_summary_embed,
)

logger = logging.getLogger(__name__)


class DiscordAlert:
    """Discord webhook client with retry and fallback.

    Attributes:
        webhook_url: Discord webhook URL.
        max_retries: Number of retry attempts (default 3).
        base_delay: Base delay in seconds for exponential backoff (default 2).
    """

    def __init__(
        self,
        webhook_url: str,
        max_retries: int = 3,
        base_delay: float = 2.0,
    ):
        self.webhook_url = webhook_url
        self.max_retries = max_retries
        self.base_delay = base_delay

    def _send(self, payload: dict) -> bool:
        """Send a payload to the Discord webhook with retry.

        Args:
            payload: Discord webhook JSON payload.

        Returns:
            True if sent successfully, False otherwise.
        """
        for attempt in range(self.max_retries):
            try:
                response = httpx.post(
                    self.webhook_url,
                    json=payload,
                    timeout=10.0,
                )
                if response.status_code in (200, 204):
                    return True

                logger.warning(
                    "Discord webhook returned %d on attempt %d",
                    response.status_code,
                    attempt + 1,
                )
            except (httpx.HTTPError, httpx.TimeoutException) as exc:
                logger.warning(
                    "Discord webhook error on attempt %d: %s",
                    attempt + 1,
                    exc,
                )

            if attempt < self.max_retries - 1:
                delay = self.base_delay * (2 ** attempt)
                time.sleep(delay)

        # All retries failed -- fallback to logging
        logger.error(
            "Discord webhook failed after %d attempts. Payload: %s",
            self.max_retries,
            payload,
        )
        return False

    def send_pick(
        self,
        parlay: dict,
        ladder: dict,
        shadow: dict,
    ) -> bool:
        """Send a pick alert.

        Args:
            parlay: Parlay dict with leg1, leg2, odds, edge.
            ladder: Ladder display dict.
            shadow: Shadow portfolio stats.

        Returns:
            True if sent successfully.
        """
        payload = format_pick_embed(parlay, ladder, shadow)
        return self._send(payload)

    def send_result(
        self,
        parlay: dict,
        result: str,
        ladder: dict,
    ) -> bool:
        """Send a result alert.

        Args:
            parlay: Parlay dict.
            result: 'won' or 'lost'.
            ladder: Ladder display dict.

        Returns:
            True if sent successfully.
        """
        payload = format_result_embed(parlay, result, ladder)
        return self._send(payload)

    def send_daily_summary(
        self,
        picks: list[dict],
        results: list[dict],
        portfolio: dict,
    ) -> bool:
        """Send end-of-day summary.

        Args:
            picks: Today's picks.
            results: Today's results.
            portfolio: Shadow portfolio stats.

        Returns:
            True if sent successfully.
        """
        payload = format_summary_embed(picks, results, portfolio)
        return self._send(payload)

    def send_no_picks(
        self,
        games_analyzed: int = 0,
        best_edge: float = 0.0,
        threshold: float = 0.02,
    ) -> bool:
        """Send a no-picks-found alert.

        Args:
            games_analyzed: Number of games analyzed.
            best_edge: Best edge found (below threshold).
            threshold: Minimum edge threshold.

        Returns:
            True if sent successfully.
        """
        payload = {
            "embeds": [
                {
                    "title": "LADDERBOT -- No Picks Today",
                    "description": (
                        f"No +EV parlays found today. "
                        f"{games_analyzed} games analyzed, best edge was "
                        f"{best_edge*100:.1f}% (below {threshold*100:.1f}% threshold)."
                    ),
                    "color": 0x95A5A6,  # Gray
                }
            ],
        }
        return self._send(payload)

    def send_model_alert(self, message: str) -> bool:
        """Send a model health alert (calibration degraded, CLV negative, etc).

        Args:
            message: Alert message text.

        Returns:
            True if sent successfully.
        """
        payload = {
            "embeds": [
                {
                    "title": "LADDERBOT -- Model Alert",
                    "description": message,
                    "color": 0xE67E22,  # Orange
                }
            ],
        }
        return self._send(payload)
