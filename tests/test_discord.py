"""Tests for Discord webhook client."""
import pytest
from unittest.mock import patch, MagicMock

from ladderbot.alerts.discord import DiscordAlert


@pytest.fixture
def alert():
    return DiscordAlert(
        webhook_url="https://discord.com/api/webhooks/123/abc",
        max_retries=3,
        base_delay=0.01,  # Fast retries for tests
    )


def _mock_response(status_code=204):
    resp = MagicMock()
    resp.status_code = status_code
    return resp


class TestDiscordAlertSend:
    @patch("ladderbot.alerts.discord.httpx.post")
    def test_successful_send(self, mock_post, alert):
        mock_post.return_value = _mock_response(204)
        result = alert._send({"content": "test"})
        assert result is True
        mock_post.assert_called_once()

    @patch("ladderbot.alerts.discord.httpx.post")
    def test_retry_on_failure(self, mock_post, alert):
        mock_post.side_effect = [
            _mock_response(500),
            _mock_response(500),
            _mock_response(204),
        ]
        result = alert._send({"content": "test"})
        assert result is True
        assert mock_post.call_count == 3

    @patch("ladderbot.alerts.discord.httpx.post")
    def test_all_retries_fail(self, mock_post, alert):
        mock_post.return_value = _mock_response(500)
        result = alert._send({"content": "test"})
        assert result is False
        assert mock_post.call_count == 3

    @patch("ladderbot.alerts.discord.httpx.post")
    def test_retry_on_exception(self, mock_post, alert):
        import httpx as httpx_mod
        mock_post.side_effect = [
            httpx_mod.TimeoutException("timeout"),
            _mock_response(204),
        ]
        result = alert._send({"content": "test"})
        assert result is True
        assert mock_post.call_count == 2

    @patch("ladderbot.alerts.discord.httpx.post")
    def test_accepts_200(self, mock_post, alert):
        mock_post.return_value = _mock_response(200)
        result = alert._send({"content": "test"})
        assert result is True


class TestDiscordAlertMethods:
    @patch("ladderbot.alerts.discord.httpx.post")
    def test_send_pick(self, mock_post, alert):
        mock_post.return_value = _mock_response(204)
        parlay = {
            "leg1": {"outcome": "BOS", "market": "h2h", "odds": -160,
                     "model_prob": 0.642, "edge": 0.031},
            "leg2": {"outcome": "Over", "market": "totals", "odds": 120,
                     "model_prob": 0.481, "edge": 0.024},
            "parlay_american": 257,
            "parlay_decimal": 3.575,
            "parlay_edge": 0.048,
        }
        ladder = {"current_step": 2, "total_steps": 4,
                  "current_bankroll": 32.50, "attempt_number": 3,
                  "starting_amount": 10.0}
        shadow = {"wins": 12, "losses": 8, "profit": 34.50, "roi": 17.3}

        result = alert.send_pick(parlay, ladder, shadow)
        assert result is True

    @patch("ladderbot.alerts.discord.httpx.post")
    def test_send_result(self, mock_post, alert):
        mock_post.return_value = _mock_response(204)
        parlay = {
            "leg1": {"outcome": "BOS", "market": "h2h", "odds": -160},
            "leg2": {"outcome": "Over", "market": "totals", "odds": 120},
            "parlay_american": 257,
        }
        ladder = {"current_step": 3, "current_bankroll": 105.63,
                  "attempt_number": 3}
        result = alert.send_result(parlay, "won", ladder)
        assert result is True

    @patch("ladderbot.alerts.discord.httpx.post")
    def test_send_daily_summary(self, mock_post, alert):
        mock_post.return_value = _mock_response(204)
        result = alert.send_daily_summary(
            picks=[{"outcome": "BOS"}],
            results=[{"outcome": "BOS", "market": "h2h", "result": "won"}],
            portfolio={"wins": 1, "losses": 0, "profit": 10.0, "roi": 100.0},
        )
        assert result is True

    @patch("ladderbot.alerts.discord.httpx.post")
    def test_send_no_picks(self, mock_post, alert):
        mock_post.return_value = _mock_response(204)
        result = alert.send_no_picks(games_analyzed=8, best_edge=0.015, threshold=0.02)
        assert result is True

    @patch("ladderbot.alerts.discord.httpx.post")
    def test_send_model_alert(self, mock_post, alert):
        mock_post.return_value = _mock_response(204)
        result = alert.send_model_alert("Brier score degraded by 15%")
        assert result is True
