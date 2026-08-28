from __future__ import annotations

from core.models.market import RegimeLabel
from core.models.trade import TradeCandidate, TradeLeg, TradeScoreBreakdown, TradeStrategy
from strategies.base import Strategy, StrategyContext, closest_strike, nearest_expiration, new_trade_id

MIN_DTE = 21
MAX_DTE = 45
LONG_LEG_MONEYNESS = 1.00
SHORT_LEG_MONEYNESS = 0.95
MIN_REGIME_CONFIDENCE = 0.55


class BearPutSpreadStrategy(Strategy):
    strategy_id = TradeStrategy.BEAR_PUT_SPREAD

    def evaluate(self, ctx: StrategyContext) -> bool:
        return (
            ctx.regime.regime == RegimeLabel.BEARISH
            and ctx.regime.confidence >= MIN_REGIME_CONFIDENCE
        )

    def build_trade(self, ctx: StrategyContext) -> TradeCandidate | None:
        today = ctx.now.date()
        expiration = nearest_expiration(ctx.chain, MIN_DTE, MAX_DTE, today)
        if expiration is None:
            return None

        puts = [c for c in ctx.chain.for_expiration(expiration) if c.right.value == "PUT"]
        if len(puts) < 2:
            return None

        long_put = closest_strike(puts, ctx.underlying_price * LONG_LEG_MONEYNESS)
        short_put = closest_strike(
            [c for c in puts if c.strike < (long_put.strike if long_put else float("inf"))],
            ctx.underlying_price * SHORT_LEG_MONEYNESS,
        )
        if long_put is None or short_put is None or short_put.strike >= long_put.strike:
            return None

        debit = long_put.mid - short_put.mid
        if debit <= 0:
            return None

        width = long_put.strike - short_put.strike
        max_loss = debit * 100
        max_profit = (width - debit) * 100
        breakeven = long_put.strike - debit

        legs = (
            TradeLeg(contract=long_put, side="BUY", quantity=1),
            TradeLeg(contract=short_put, side="SELL", quantity=1),
        )

        score = TradeScoreBreakdown(
            market_regime=ctx.regime.confidence * 25,
            options_signal=15.0,
            volatility_edge=10.0,
            momentum=max(0.0, -ctx.regime.features.get("momentum_10d", 0.0)) * 100,
            liquidity=10.0 if max(long_put.spread_pct, short_put.spread_pct) < 0.08 else 5.0,
            risk_reward=min(10.0, (max_profit / max_loss) * 3) if max_loss > 0 else 0.0,
            news_catalyst=0.0,
        )

        return TradeCandidate(
            trade_id=new_trade_id(),
            symbol=ctx.symbol,
            strategy=self.strategy_id,
            legs=legs,
            rationale=(
                f"Regime BEARISH (confidence {ctx.regime.confidence:.0%}). "
                f"Buy {long_put.strike} / Sell {short_put.strike} put spread, "
                f"{width:.0f}-wide, {(expiration - today).days} DTE. "
                f"Debit ${debit:.2f}, max profit ${max_profit:.2f}, max loss ${max_loss:.2f}."
            ),
            max_profit=round(max_profit, 2),
            max_loss=round(max_loss, 2),
            breakeven=(round(breakeven, 2),),
            probability_estimate=None,
            score=score,
            size_tier=None,
            created_at=ctx.now,
        )

    def validate(self, ctx: StrategyContext, candidate: TradeCandidate) -> tuple[bool, list[str]]:
        problems = self._base_validate_legs(candidate)
        long_leg, short_leg = candidate.legs[0], candidate.legs[1]
        if long_leg.contract.strike <= short_leg.contract.strike:
            problems.append("long strike must be above short strike")
        if candidate.max_loss <= 0:
            problems.append("max_loss must be positive (net debit required)")
        if candidate.max_profit <= 0:
            problems.append("max_profit must be positive")
        return len(problems) == 0, problems
