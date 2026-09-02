"""
Exit engine (Day-4 Phase 8).

Hold-to-expiration remains the default and the only exit rule available
for ANY dataset. Early-exit rules (profit target, max loss, time-based)
require repricing the position's current mark-to-market value on a day
before expiration — and per backtest/pnl.py's mark_to_market_path(), that
repricing is ONLY possible for SYNTHETIC_OPTIONS_DATA today, because it
needs a pricing MODEL, not just a data snapshot (real datasets don't
guarantee the same contract is quoted on every day of the holding
period). So: early-exit rules are silently downgraded to
hold-to-expiration for any non-synthetic dataset, WITH A LOGGED REASON —
never silently pretending to have exited early on data that can't
support it.

REGIME_REVERSAL exit (mentioned in the spec) is NOT implemented in this
pass — it would require re-running regime classification inside the
per-day position-holding loop for every open position, which is a larger
architectural change to backtest/runner.py than time allowed here. Noted
as a Known Limitation, not silently dropped.

Look-ahead safety: every exit check for day T uses ONLY
data/market/synthetic_source.py's model repriced with information
available as of T (trailing realized vol, that day's spot) — the exact
same leakage boundary decide_at() enforces elsewhere.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum

from backtest.data_schema import DataProvenance, HistoricalDataset
from core.models.trade import TradeCandidate


class ExitRuleType(str, Enum):
    EXPIRATION = "EXPIRATION"
    PROFIT_TARGET = "PROFIT_TARGET"
    MAX_LOSS = "MAX_LOSS"
    TIME_BASED = "TIME_BASED"


@dataclass(frozen=True, slots=True)
class ExitConfig:
    rule: ExitRuleType = ExitRuleType.EXPIRATION
    profit_target_pct_of_max_profit: float = 0.50  # close at 50% of theoretical max profit, a common convention
    max_loss_pct_of_max_loss: float = 1.00  # close at 100% of defined max loss (i.e. don't hold past the worst case)
    time_based_days: int = 10


def reprice_position(candidate: TradeCandidate, dataset: HistoricalDataset, as_of: date) -> float | None:
    """Returns the position's current mark-to-market P&L (vs. entry), or
    None if this dataset can't support repricing (see module docstring)."""
    if dataset.provenance != DataProvenance.SYNTHETIC_OPTIONS_DATA:
        return None

    from backtest.pnl import COST_BASE, _leg_entry_price
    from data.market.synthetic_source import RISK_FREE_RATE, _black_scholes, _trailing_realized_vol

    closes_by_date = {d.as_of_date: d.underlying_close for d in dataset.days}
    all_dates = sorted(closes_by_date.keys())
    if as_of not in closes_by_date:
        return None
    idx = all_dates.index(as_of)
    trailing = [closes_by_date[d] for d in all_dates[: idx + 1]]
    spot = trailing[-1]
    vol = _trailing_realized_vol(trailing)

    entry_net = sum(
        (_leg_entry_price(leg, COST_BASE) if leg.side == "BUY" else -_leg_entry_price(leg, COST_BASE))
        for leg in candidate.legs
    )
    mark_net = 0.0
    for leg in candidate.legs:
        dte = (leg.contract.expiration - as_of).days
        t_years = max(dte, 0) / 365.0
        price = _black_scholes(spot, leg.contract.strike, t_years, vol, leg.contract.right, RISK_FREE_RATE)
        mark_net += price if leg.side == "BUY" else -price

    return (mark_net - entry_net) * 100  # per-contract, quantity applied by the caller


def check_early_exit(
    candidate: TradeCandidate, dataset: HistoricalDataset, as_of: date, entry_date: date, config: ExitConfig
) -> tuple[bool, str | None]:
    """Returns (should_exit, reason). Never raises on unsupported data —
    just declines to exit early, which falls through to expiration."""
    if config.rule == ExitRuleType.EXPIRATION:
        return False, None

    if dataset.provenance != DataProvenance.SYNTHETIC_OPTIONS_DATA:
        return False, "early-exit rule requested but dataset provenance does not support leakage-safe repricing"

    if config.rule == ExitRuleType.TIME_BASED:
        if (as_of - entry_date).days >= config.time_based_days:
            return True, f"time_based: held {(as_of - entry_date).days}d >= {config.time_based_days}d threshold"
        return False, None

    mtm_pnl = reprice_position(candidate, dataset, as_of)
    if mtm_pnl is None:
        return False, "repricing returned None for this date"

    if config.rule == ExitRuleType.PROFIT_TARGET:
        max_profit = candidate.max_profit if candidate.max_profit != float("inf") else None
        if max_profit is not None:
            target = max_profit * config.profit_target_pct_of_max_profit
            if mtm_pnl >= target:
                return True, f"profit_target: mtm_pnl={mtm_pnl:.2f} >= target={target:.2f}"
        return False, None

    if config.rule == ExitRuleType.MAX_LOSS:
        threshold = -abs(candidate.max_loss * config.max_loss_pct_of_max_loss)
        if mtm_pnl <= threshold:
            return True, f"max_loss: mtm_pnl={mtm_pnl:.2f} <= threshold={threshold:.2f}"
        return False, None

    return False, None
