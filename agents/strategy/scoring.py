"""
Transparent, configurable trade scoring (spec: "Trade Score" section).

Weights and thresholds live in Settings — nothing here is hardcoded.
The score is a *sizing signal*, not a probability of profit; the
Risk Sentinel is the actual gate.
"""
from __future__ import annotations

from core.config.settings import Settings
from core.models.trade import SizeTier, TradeScoreBreakdown


def score_trade(
    *,
    market_regime_signal: float,   # 0-100 raw sub-scores, already computed by callers
    options_signal: float,
    volatility_edge: float,
    momentum: float,
    liquidity: float,
    risk_reward: float,
    news_catalyst: float,
    settings: Settings,
) -> TradeScoreBreakdown:
    w = settings.scoring_weights
    return TradeScoreBreakdown(
        market_regime=round(market_regime_signal * w["market_regime"], 2),
        options_signal=round(options_signal * w["options_signal"], 2),
        volatility_edge=round(volatility_edge * w["volatility_edge"], 2),
        momentum=round(momentum * w["momentum"], 2),
        liquidity=round(liquidity * w["liquidity"], 2),
        risk_reward=round(risk_reward * w["risk_reward"], 2),
        news_catalyst=round(news_catalyst * w["news_catalyst"], 2),
    )


def size_tier_for_score(total_score: float, settings: Settings) -> SizeTier:
    if total_score < settings.score_no_trade_max:
        return SizeTier.NO_TRADE
    if total_score < settings.score_small_size_max:
        return SizeTier.SMALL_SIZE
    if total_score < settings.score_normal_size_max:
        return SizeTier.NORMAL_SIZE
    return SizeTier.HIGH_CONVICTION_SIZE
