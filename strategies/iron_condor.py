from __future__ import annotations

from core.models.market import RegimeLabel
from core.models.trade import TradeCandidate, TradeLeg, TradeScoreBreakdown, TradeStrategy
from strategies.base import Strategy, StrategyContext, closest_strike, nearest_expiration, new_trade_id

MIN_DTE = 21
MAX_DTE = 45
SHORT_PUT_MONEYNESS = 0.93
LONG_PUT_MONEYNESS = 0.88
SHORT_CALL_MONEYNESS = 1.07
LONG_CALL_MONEYNESS = 1.12
MIN_REGIME_CONFIDENCE = 0.55
MIN_IV_FOR_CONDOR = 0.20  # only sell premium when IV is rich enough to be worth the tail risk


class IronCondorStrategy(Strategy):
    strategy_id = TradeStrategy.IRON_CONDOR

    def evaluate(self, ctx: StrategyContext) -> bool:
        if ctx.regime.regime != RegimeLabel.RANGE or ctx.regime.confidence < MIN_REGIME_CONFIDENCE:
            return False
        iv_proxy = ctx.regime.features.get("realized_vol_annualized", 0.0)
        return iv_proxy >= MIN_IV_FOR_CONDOR

    def build_trade(self, ctx: StrategyContext) -> TradeCandidate | None:
        today = ctx.now.date()
        expiration = nearest_expiration(ctx.chain, MIN_DTE, MAX_DTE, today)
        if expiration is None:
            return None

        leg_contracts = ctx.chain.for_expiration(expiration)
        calls = [c for c in leg_contracts if c.right.value == "CALL"]
        puts = [c for c in leg_contracts if c.right.value == "PUT"]
        if len(calls) < 2 or len(puts) < 2:
            return None

        short_put = closest_strike(puts, ctx.underlying_price * SHORT_PUT_MONEYNESS)
        long_put = closest_strike(
            [c for c in puts if short_put and c.strike < short_put.strike],
            ctx.underlying_price * LONG_PUT_MONEYNESS,
        )
        short_call = closest_strike(calls, ctx.underlying_price * SHORT_CALL_MONEYNESS)
        long_call = closest_strike(
            [c for c in calls if short_call and c.strike > short_call.strike],
            ctx.underlying_price * LONG_CALL_MONEYNESS,
        )
        if None in (short_put, long_put, short_call, long_call):
            return None
        if not (long_put.strike < short_put.strike < short_call.strike < long_call.strike):
            return None

        credit = (short_put.mid - long_put.mid) + (short_call.mid - long_call.mid)
        if credit <= 0:
            return None

        put_width = short_put.strike - long_put.strike
        call_width = long_call.strike - short_call.strike
        max_width = max(put_width, call_width)
        max_loss = (max_width - credit) * 100
        max_profit = credit * 100
        if max_loss <= 0:
            return None

        legs = (
            TradeLeg(contract=long_put, side="BUY", quantity=1),
            TradeLeg(contract=short_put, side="SELL", quantity=1),
            TradeLeg(contract=short_call, side="SELL", quantity=1),
            TradeLeg(contract=long_call, side="BUY", quantity=1),
        )

        worst_spread_pct = max(c.spread_pct for c in (long_put, short_put, short_call, long_call))

        score = TradeScoreBreakdown(
            market_regime=ctx.regime.confidence * 25,
            options_signal=15.0,
            volatility_edge=min(15.0, ctx.regime.features.get("realized_vol_annualized", 0.0) * 40),
            momentum=5.0,  # low weight — range strategies want LOW directional conviction
            liquidity=10.0 if worst_spread_pct < 0.10 else 4.0,
            risk_reward=min(10.0, (max_profit / max_loss) * 4) if max_loss > 0 else 0.0,
            news_catalyst=0.0,
        )

        return TradeCandidate(
            trade_id=new_trade_id(),
            symbol=ctx.symbol,
            strategy=self.strategy_id,
            legs=legs,
            rationale=(
                f"Regime RANGE (confidence {ctx.regime.confidence:.0%}), elevated realized vol. "
                f"Iron condor {long_put.strike}/{short_put.strike}/{short_call.strike}/{long_call.strike}, "
                f"{(expiration - today).days} DTE. Credit ${credit:.2f}, "
                f"max profit ${max_profit:.2f}, max loss ${max_loss:.2f}."
            ),
            max_profit=round(max_profit, 2),
            max_loss=round(max_loss, 2),
            breakeven=(
                round(short_put.strike - credit, 2),
                round(short_call.strike + credit, 2),
            ),
            probability_estimate=None,
            score=score,
            size_tier=None,
            created_at=ctx.now,
        )

    def validate(self, ctx: StrategyContext, candidate: TradeCandidate) -> tuple[bool, list[str]]:
        problems = self._base_validate_legs(candidate)
        strikes = [leg.contract.strike for leg in candidate.legs]
        if strikes != sorted(strikes):
            problems.append("iron condor legs are not in ascending strike order")
        if len(candidate.legs) != 4:
            problems.append("iron condor requires exactly 4 legs")
        if candidate.max_loss <= 0 or candidate.max_profit <= 0:
            problems.append("max_profit and max_loss must both be positive and defined")
        return len(problems) == 0, problems
