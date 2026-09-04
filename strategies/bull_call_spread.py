from __future__ import annotations

from core.models.market import RegimeLabel
from core.models.trade import TradeCandidate, TradeLeg, TradeScoreBreakdown, TradeStrategy
from strategies.base import (
    Strategy,
    StrategyContext,
    closest_strike,
    nearest_expiration,
    new_trade_id,
)

MIN_DTE = 21
MAX_DTE = 45
LONG_LEG_MONEYNESS = 1.00   # at-the-money long call
SHORT_LEG_MONEYNESS = 1.05  # ~5% OTM short call
MIN_REGIME_CONFIDENCE = 0.55


class BullCallSpreadStrategy(Strategy):
    strategy_id = TradeStrategy.BULL_CALL_SPREAD

    def evaluate(self, ctx: StrategyContext) -> bool:
        return (
            ctx.regime.regime == RegimeLabel.BULLISH
            and ctx.regime.confidence >= MIN_REGIME_CONFIDENCE
        )

    def build_trade(self, ctx: StrategyContext) -> TradeCandidate | None:
        today = ctx.now.date()
        expiration = nearest_expiration(ctx.chain, MIN_DTE, MAX_DTE, today)
        if expiration is None:
            return None

        calls = [c for c in ctx.chain.for_expiration(expiration) if c.right.value == "CALL"]
        if len(calls) < 2:
            return None

        long_call = closest_strike(calls, ctx.underlying_price * LONG_LEG_MONEYNESS)
        short_call = closest_strike(
            [c for c in calls if c.strike > (long_call.strike if long_call else 0)],
            ctx.underlying_price * SHORT_LEG_MONEYNESS,
        )
        if long_call is None or short_call is None or short_call.strike <= long_call.strike:
            return None

        debit = long_call.mid - short_call.mid
        if debit <= 0:
            return None

        width = short_call.strike - long_call.strike
        max_loss = debit * 100
        max_profit = (width - debit) * 100
        breakeven = long_call.strike + debit

        legs = (
            TradeLeg(contract=long_call, side="BUY", quantity=1),
            TradeLeg(contract=short_call, side="SELL", quantity=1),
        )

        score = TradeScoreBreakdown(
            market_regime=ctx.regime.confidence * 25,
            options_signal=15.0,
            volatility_edge=10.0,
            momentum=max(0.0, ctx.regime.features.get("momentum_10d", 0.0)) * 100,
            liquidity=10.0 if max(long_call.spread_pct, short_call.spread_pct) < 0.08 else 5.0,
            risk_reward=min(10.0, (max_profit / max_loss) * 3) if max_loss > 0 else 0.0,
            news_catalyst=0.0,
        )

        return TradeCandidate(
            trade_id=new_trade_id(),
            symbol=ctx.symbol,
            strategy=self.strategy_id,
            legs=legs,
            rationale=(
                f"Regime BULLISH (confidence {ctx.regime.confidence:.0%}). "
                f"Buy {long_call.strike} / Sell {short_call.strike} call spread, "
                f"{width:.0f}-wide, {(expiration - today).days} DTE. "
                f"Debit ${debit:.2f}, max profit ${max_profit:.2f}, max loss ${max_loss:.2f}."
            ),
            max_profit=round(max_profit, 2),
            max_loss=round(max_loss, 2),
            breakeven=(round(breakeven, 2),),
            probability_estimate=None,
            score=score,
            size_tier=None,  # assigned by the strategy selector after scoring
            created_at=ctx.now,
        )

    def validate(self, ctx: StrategyContext, candidate: TradeCandidate) -> tuple[bool, list[str]]:
        problems = self._base_validate_legs(candidate)
        long_leg, short_leg = candidate.legs[0], candidate.legs[1]
        if long_leg.contract.strike >= short_leg.contract.strike:
            problems.append("long strike must be below short strike")
        if candidate.max_loss <= 0:
            problems.append("max_loss must be positive (net debit required)")
        if candidate.max_profit <= 0:
            problems.append("max_profit must be positive")
        return len(problems) == 0, problems
