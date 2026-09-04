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

MIN_DTE = 14
MAX_DTE = 35
MIN_REGIME_CONFIDENCE = 0.65          # deliberately stricter than the directional strategies
MAX_DEBIT_AS_PCT_OF_EQUITY = 0.01     # spec: "strict maximum-risk control"


class LongVolatilityStrategy(Strategy):
    """
    Spec is explicit: use ONLY under carefully defined conditions — major
    catalyst, unusually favorable vol setup, strict max-risk control.
    This is deliberately the most conservative and least-frequently-
    eligible strategy in the system; it should not fire on every
    HIGH_VOLATILITY reading.
    """

    strategy_id = TradeStrategy.LONG_VOLATILITY

    def evaluate(self, ctx: StrategyContext) -> bool:
        return (
            ctx.regime.regime == RegimeLabel.HIGH_VOLATILITY
            and ctx.regime.confidence >= MIN_REGIME_CONFIDENCE
        )

    def build_trade(self, ctx: StrategyContext) -> TradeCandidate | None:
        today = ctx.now.date()
        expiration = nearest_expiration(ctx.chain, MIN_DTE, MAX_DTE, today)
        if expiration is None:
            return None

        leg_contracts = ctx.chain.for_expiration(expiration)
        calls = [c for c in leg_contracts if c.right.value == "CALL"]
        puts = [c for c in leg_contracts if c.right.value == "PUT"]
        if not calls or not puts:
            return None

        atm_call = closest_strike(calls, ctx.underlying_price)
        atm_put = closest_strike(puts, ctx.underlying_price)
        if atm_call is None or atm_put is None:
            return None

        debit = atm_call.mid + atm_put.mid
        if debit <= 0:
            return None

        max_loss_per_contract = debit * 100

        # NOTE: the Risk Sentinel re-checks this against *real* portfolio equity —
        # this local check exists so the strategy itself never even proposes an
        # obviously oversized long-vol trade, per the "strict maximum-risk
        # control" requirement in the spec. 100_000 is a placeholder equity
        # scale used only to keep the strategy self-limiting in isolation.
        max_risk_budget = ctx.settings.max_trade_risk_pct * 100_000
        if max_loss_per_contract > max_risk_budget:
            return None

        legs = (
            TradeLeg(contract=atm_call, side="BUY", quantity=1),
            TradeLeg(contract=atm_put, side="BUY", quantity=1),
        )

        upper_breakeven = atm_call.strike + debit
        lower_breakeven = atm_put.strike - debit

        score = TradeScoreBreakdown(
            market_regime=ctx.regime.confidence * 25,
            options_signal=10.0,   # intentionally conservative — this strategy needs a real catalyst,
            volatility_edge=15.0,  # not just a numeric regime read, to score well end-to-end.
            momentum=0.0,
            liquidity=8.0 if max(atm_call.spread_pct, atm_put.spread_pct) < 0.08 else 2.0,
            risk_reward=5.0,       # capped low: theoretically unlimited upside, but time-decay risk is real
            news_catalyst=0.0,     # populated externally when a catalyst feed is wired in
        )

        return TradeCandidate(
            trade_id=new_trade_id(),
            symbol=ctx.symbol,
            strategy=self.strategy_id,
            legs=legs,
            rationale=(
                f"Regime HIGH_VOLATILITY (confidence {ctx.regime.confidence:.0%}). "
                f"ATM straddle at {atm_call.strike}, {(expiration - today).days} DTE. "
                f"Debit ${debit:.2f} (${max_loss_per_contract:.2f} max loss per contract) — "
                "sized to respect strict long-vol risk control, not scaled up on conviction alone."
            ),
            max_profit=float("inf"),  # theoretically uncapped; Risk Sentinel and journal must render this clearly
            max_loss=round(max_loss_per_contract, 2),
            breakeven=(round(lower_breakeven, 2), round(upper_breakeven, 2)),
            probability_estimate=None,
            score=score,
            size_tier=None,
            created_at=ctx.now,
        )

    def validate(self, ctx: StrategyContext, candidate: TradeCandidate) -> tuple[bool, list[str]]:
        problems = self._base_validate_legs(candidate)
        if len(candidate.legs) != 2:
            problems.append("long volatility straddle requires exactly 2 legs")
        if candidate.max_loss <= 0:
            problems.append("max_loss must be positive")
        if candidate.max_loss > MAX_DEBIT_AS_PCT_OF_EQUITY * 100_000:
            problems.append(
                "debit exceeds the strategy's local strict-risk-control ceiling "
                "(Risk Sentinel will independently re-check against real equity)"
            )
        return len(problems) == 0, problems
