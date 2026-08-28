from __future__ import annotations

import pytest

from agents.strategy.scoring import score_trade, size_tier_for_score
from core.models.trade import SizeTier


def test_score_weights_are_applied_correctly(settings):
    score = score_trade(
        market_regime_signal=100, options_signal=100, volatility_edge=100,
        momentum=100, liquidity=100, risk_reward=100, news_catalyst=100,
        settings=settings,
    )
    # All sub-scores maxed out (100) with weights summing to 1.0 => total should be 100.
    assert score.total == pytest.approx(100.0, abs=0.01)


def test_score_breakdown_reflects_individual_weights(settings):
    score = score_trade(
        market_regime_signal=100, options_signal=0, volatility_edge=0,
        momentum=0, liquidity=0, risk_reward=0, news_catalyst=0,
        settings=settings,
    )
    assert score.market_regime == pytest.approx(25.0, abs=0.01)
    assert score.total == pytest.approx(25.0, abs=0.01)


@pytest.mark.parametrize(
    "total,expected_tier",
    [
        (10.0, SizeTier.NO_TRADE),
        (59.9, SizeTier.NO_TRADE),
        (60.0, SizeTier.SMALL_SIZE),
        (69.9, SizeTier.SMALL_SIZE),
        (70.0, SizeTier.NORMAL_SIZE),
        (84.9, SizeTier.NORMAL_SIZE),
        (85.0, SizeTier.HIGH_CONVICTION_SIZE),
        (99.0, SizeTier.HIGH_CONVICTION_SIZE),
    ],
)
def test_size_tier_thresholds(settings, total, expected_tier):
    assert size_tier_for_score(total, settings) == expected_tier


def test_size_tier_thresholds_are_configurable(settings):
    settings.score_no_trade_max = 50
    settings.score_small_size_max = 60
    settings.score_normal_size_max = 75
    assert size_tier_for_score(55, settings) == SizeTier.SMALL_SIZE
    assert size_tier_for_score(80, settings) == SizeTier.HIGH_CONVICTION_SIZE
