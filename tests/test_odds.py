"""Tests for odds math utilities."""
import pytest
from ladderbot.utils.odds import (
    american_to_decimal,
    decimal_to_american,
    implied_probability,
    parlay_decimal_odds,
    parlay_american_odds,
    calculate_edge,
    classify_confidence,
    ladder_steps_needed,
)


class TestAmericanToDecimal:
    def test_positive_odds(self):
        assert american_to_decimal(200) == pytest.approx(3.0)

    def test_negative_odds(self):
        # -150 means bet $150 to win $100, so decimal = 1 + 100/150 = 1.6667
        assert american_to_decimal(-150) == pytest.approx(1.6667, rel=1e-3)

    def test_even_money_positive(self):
        assert american_to_decimal(100) == pytest.approx(2.0)

    def test_heavy_favorite(self):
        assert american_to_decimal(-300) == pytest.approx(1.3333, rel=1e-3)

    def test_big_underdog(self):
        assert american_to_decimal(500) == pytest.approx(6.0)

    def test_zero_raises(self):
        with pytest.raises(ValueError):
            american_to_decimal(0)


class TestDecimalToAmerican:
    def test_positive_american(self):
        assert decimal_to_american(3.0) == 200

    def test_negative_american(self):
        assert decimal_to_american(1.5) == -200

    def test_even_money(self):
        assert decimal_to_american(2.0) == 100

    def test_heavy_favorite(self):
        assert decimal_to_american(1.25) == -400

    def test_below_one_raises(self):
        with pytest.raises(ValueError):
            decimal_to_american(0.9)

    def test_exactly_one_raises(self):
        with pytest.raises(ValueError):
            decimal_to_american(1.0)


class TestImpliedProbability:
    def test_even_money(self):
        assert implied_probability(100) == pytest.approx(0.5)

    def test_favorite(self):
        # -200 implies 200/(200+100) = 66.67%
        assert implied_probability(-200) == pytest.approx(0.6667, rel=1e-3)

    def test_underdog(self):
        # +200 implies 100/(200+100) = 33.33%
        assert implied_probability(200) == pytest.approx(0.3333, rel=1e-3)

    def test_heavy_favorite(self):
        # -400 implies 400/500 = 80%
        assert implied_probability(-400) == pytest.approx(0.8)

    def test_slight_underdog(self):
        # +110 implies 100/210 = 47.62%
        assert implied_probability(110) == pytest.approx(0.4762, rel=1e-3)

    def test_zero_raises(self):
        with pytest.raises(ValueError):
            implied_probability(0)


class TestParlayDecimalOdds:
    def test_two_legs(self):
        # 1.625 * 2.20 = 3.575
        assert parlay_decimal_odds([1.625, 2.20]) == pytest.approx(3.575)

    def test_three_legs(self):
        assert parlay_decimal_odds([2.0, 2.0, 2.0]) == pytest.approx(8.0)

    def test_single_leg(self):
        assert parlay_decimal_odds([3.0]) == pytest.approx(3.0)

    def test_empty_raises(self):
        with pytest.raises(ValueError):
            parlay_decimal_odds([])


class TestParlayAmericanOdds:
    def test_two_positive_legs(self):
        # -160 (1.625) * +120 (2.20) = 3.575 -> +258 (rounded)
        result = parlay_american_odds([-160, 120])
        assert result == 258  # (3.575 - 1) * 100 = 257.5 -> round to 258

    def test_two_favorites(self):
        # -150 (1.667) * -130 (1.769) = 2.949 -> +195
        result = parlay_american_odds([-150, -130])
        assert result == 195

    def test_zero_leg_raises(self):
        with pytest.raises(ValueError):
            parlay_american_odds([0, 100])


class TestCalculateEdge:
    def test_positive_edge(self):
        # Model says 64%, book implies 61.5% (-160)
        edge = calculate_edge(0.642, -160)
        # implied_prob(-160) = 160/260 = 0.6154
        assert edge == pytest.approx(0.0266, rel=1e-2)

    def test_negative_edge(self):
        # Model says 40%, book implies 50% (+100)
        edge = calculate_edge(0.40, 100)
        assert edge == pytest.approx(-0.10, rel=1e-2)

    def test_zero_edge(self):
        # Model says 50%, book implies 50% (+100)
        edge = calculate_edge(0.50, 100)
        assert edge == pytest.approx(0.0)


class TestClassifyConfidence:
    def test_low(self):
        assert classify_confidence(0.025, cold_start=False) == "LOW"

    def test_medium(self):
        assert classify_confidence(0.04, cold_start=False) == "MEDIUM"

    def test_high(self):
        assert classify_confidence(0.06, cold_start=False) == "HIGH"

    def test_boundary_low_medium(self):
        assert classify_confidence(0.03, cold_start=False) == "MEDIUM"

    def test_boundary_medium_high(self):
        assert classify_confidence(0.05, cold_start=False) == "HIGH"

    def test_cold_start_caps_at_medium(self):
        # Even 8% edge should be capped at MEDIUM during cold start
        assert classify_confidence(0.08, cold_start=True) == "MEDIUM"

    def test_cold_start_low_stays_low(self):
        assert classify_confidence(0.025, cold_start=True) == "LOW"

    def test_below_threshold(self):
        assert classify_confidence(0.01, cold_start=False) == "LOW"


class TestLadderStepsNeeded:
    def test_standard_ladder(self):
        # $10 -> $1000 at +225 (3.25 decimal)
        # ceil(log(1000/10) / log(3.25)) = ceil(4.612/1.179) = ceil(3.912) = 4
        assert ladder_steps_needed(10.0, 1000.0, 3.25) == 4

    def test_even_money(self):
        # $10 -> $1000 at 2.0 decimal
        # ceil(log(100) / log(2)) = ceil(6.644) = 7
        assert ladder_steps_needed(10.0, 1000.0, 2.0) == 7

    def test_already_at_target(self):
        assert ladder_steps_needed(1000.0, 1000.0, 3.0) == 0

    def test_above_target(self):
        assert ladder_steps_needed(1500.0, 1000.0, 3.0) == 0

    def test_one_step(self):
        # $500 -> $1000 at 3.0 decimal -> ceil(log(2)/log(3)) = ceil(0.631) = 1
        assert ladder_steps_needed(500.0, 1000.0, 3.0) == 1

    def test_odds_of_one_raises(self):
        with pytest.raises(ValueError):
            ladder_steps_needed(10.0, 1000.0, 1.0)
