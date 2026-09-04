"""
Strategy Agent (Agent 4).

Runs every registered strategy's `evaluate()`, builds trades for the
eligible ones, scores them, and returns the single best TradeCandidate
(or None — "no trade" is a valid and expected output). The agent must
be able to explain why a strategy was chosen; `rationale` on the
TradeCandidate carries that explanation into the journal and dashboard.
"""
from __future__ import annotations

import logging

from core.config.settings import Settings
from core.models.trade import TradeCandidate
from strategies.base import Strategy, StrategyContext
from strategies.bear_put_spread import BearPutSpreadStrategy
from strategies.bull_call_spread import BullCallSpreadStrategy
from strategies.iron_condor import IronCondorStrategy
from strategies.long_volatility import LongVolatilityStrategy

logger = logging.getLogger("optionsentinel.strategy")

DEFAULT_STRATEGIES: tuple[Strategy, ...] = (
    BullCallSpreadStrategy(),
    BearPutSpreadStrategy(),
    IronCondorStrategy(),
    LongVolatilityStrategy(),
)


def _apply_size_tier(candidate: TradeCandidate, settings: Settings) -> TradeCandidate:
    from dataclasses import replace

    from agents.strategy.scoring import size_tier_for_score

    tier = size_tier_for_score(candidate.score.total, settings)
    return replace(candidate, size_tier=tier)


class StrategySelector:
    def __init__(self, settings: Settings, strategies: tuple[Strategy, ...] = DEFAULT_STRATEGIES):
        self.settings = settings
        self.strategies = strategies

    def select(self, ctx: StrategyContext) -> TradeCandidate | None:
        eligible = [s for s in self.strategies if s.evaluate(ctx)]
        if not eligible:
            logger.info("STRATEGY_SELECTED symbol=%s result=NONE (no eligible strategy for regime %s)",
                        ctx.symbol, ctx.regime.regime.value)
            return None

        candidates: list[TradeCandidate] = []
        for strategy in eligible:
            candidate = strategy.build_trade(ctx)
            if candidate is None:
                continue
            ok, problems = strategy.validate(ctx, candidate)
            if not ok:
                logger.warning("STRATEGY_VALIDATION_FAILED strategy=%s problems=%s",
                                strategy.strategy_id.value, problems)
                continue
            candidates.append(_apply_size_tier(candidate, self.settings))

        if not candidates:
            logger.info("STRATEGY_SELECTED symbol=%s result=NONE (no valid tradeable contracts)", ctx.symbol)
            return None

        # Highest total score wins; NO_TRADE-tier candidates are still returned
        # so the caller/journal can record *why* nothing was sized, rather
        # than silently dropping the analysis.
        best = max(candidates, key=lambda c: c.score.total)
        logger.info(
            "STRATEGY_SELECTED symbol=%s strategy=%s score=%.2f tier=%s",
            ctx.symbol, best.strategy.value, best.score.total, best.size_tier.value,
        )
        return best
