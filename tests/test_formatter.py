"""Tests for Discord embed formatter."""
import pytest

from ladderbot.alerts.formatter import (
    format_pick_embed,
    format_result_embed,
    format_summary_embed,
)


def _make_parlay():
    return {
        "leg1": {
            "game_id": "nba_g1",
            "outcome": "BOS",
            "market": "h2h",
            "odds": -160,
            "model_prob": 0.642,
            "edge": 0.031,
        },
        "leg2": {
            "game_id": "nhl_g2",
            "outcome": "Over",
            "market": "totals",
            "odds": 120,
            "model_prob": 0.481,
            "edge": 0.024,
        },
        "parlay_american": 257,
        "parlay_decimal": 3.575,
        "parlay_edge": 0.048,
    }


def _make_ladder():
    return {
        "status": "ACTIVE",
        "current_step": 2,
        "total_steps": 4,
        "current_bankroll": 32.50,
        "attempt_number": 3,
        "starting_amount": 10.0,
        "target_amount": 1000.0,
    }


def _make_shadow():
    return {
        "wins": 12,
        "losses": 8,
        "profit": 34.50,
        "roi": 17.3,
    }


class TestFormatPickEmbed:
    def test_returns_dict_with_embeds(self):
        result = format_pick_embed(_make_parlay(), _make_ladder(), _make_shadow())
        assert "embeds" in result
        assert len(result["embeds"]) == 1

    def test_title_contains_step(self):
        result = format_pick_embed(_make_parlay(), _make_ladder(), _make_shadow())
        title = result["embeds"][0]["title"]
        assert "Step 2 of 4" in title

    def test_description_contains_legs(self):
        result = format_pick_embed(_make_parlay(), _make_ladder(), _make_shadow())
        desc = result["embeds"][0]["description"]
        assert "BOS" in desc
        assert "Over" in desc
        assert "+257" in desc

    def test_description_contains_shadow_stats(self):
        result = format_pick_embed(_make_parlay(), _make_ladder(), _make_shadow())
        desc = result["embeds"][0]["description"]
        assert "12W-8L" in desc
        assert "34.50" in desc

    def test_description_contains_odds_note(self):
        result = format_pick_embed(_make_parlay(), _make_ladder(), _make_shadow())
        desc = result["embeds"][0]["description"]
        assert "Verify" in desc or "DraftKings" in desc

    def test_has_color(self):
        result = format_pick_embed(_make_parlay(), _make_ladder(), _make_shadow())
        assert "color" in result["embeds"][0]


class TestFormatResultEmbed:
    def test_win_result(self):
        result = format_result_embed(_make_parlay(), "won", _make_ladder())
        assert "WIN" in result["embeds"][0]["title"]
        assert result["embeds"][0]["color"] == 0x00FF00

    def test_loss_result(self):
        result = format_result_embed(_make_parlay(), "lost", _make_ladder())
        assert "LOSS" in result["embeds"][0]["title"]
        assert result["embeds"][0]["color"] == 0xFF0000

    def test_contains_legs(self):
        result = format_result_embed(_make_parlay(), "won", _make_ladder())
        desc = result["embeds"][0]["description"]
        assert "BOS" in desc
        assert "Over" in desc


class TestFormatSummaryEmbed:
    def test_returns_summary(self):
        picks = [{"outcome": "BOS"}, {"outcome": "NYR"}]
        results = [
            {"outcome": "BOS", "market": "h2h", "result": "won"},
            {"outcome": "NYR", "market": "h2h", "result": "lost"},
        ]
        result = format_summary_embed(picks, results, _make_shadow())
        assert "Daily Summary" in result["embeds"][0]["title"]

    def test_contains_record(self):
        picks = [{"outcome": "BOS"}]
        results = [{"outcome": "BOS", "market": "h2h", "result": "won"}]
        result = format_summary_embed(picks, results, _make_shadow())
        desc = result["embeds"][0]["description"]
        assert "1W-0L" in desc

    def test_empty_results(self):
        result = format_summary_embed([], [], _make_shadow())
        desc = result["embeds"][0]["description"]
        assert "0W-0L" in desc
