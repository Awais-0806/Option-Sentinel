"""
P&L integrity (Phase N).

Explicit requirement from the spec: "For spreads, calculate P&L from the
individual legs rather than assuming a single-leg price." This module
does exactly that — every function operates leg-by-leg and sums.

Two P&L modes, and callers must be explicit about which they're getting:

  entry_to_expiration_pnl() — terminal payoff at expiration, computed from
    intrinsic value only (correct for European-style cash-settled index
    options; a disclosed simplification for American-style equity options
    where early assignment could occur — see docs/ARCHITECTURE.md). Works
    for ANY dataset (real or synthetic), since it only needs the
    underlying's price on the expiration date.

  mark_to_market_path() — a full daily P&L path between entry and exit,
    used for max favorable/adverse excursion (MFE/MAE). This is ONLY
    computed for SYNTHETIC_OPTIONS_DATA, because it requires repricing the
    exact same contract on every day of the holding period, which needs a
    pricing MODEL, not just a data snapshot. Real datasets (CSV/Alpaca)
    would need every day of the holding period to independently quote the
    exact same contract, which is not guaranteed by any data source this
    project has integrated — see Known Limitations in the Day-3 report.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from backtest.data_schema import DataProvenance, HistoricalDataset
from core.models.options import OptionRight
from core.models.trade import TradeCandidate

CONTRACT_MULTIPLIER = 100


@dataclass(frozen=True, slots=True)
class CostAssumptions:
    """Phase K: kept separate from quote generation so they can be swept independently."""
    commission_per_contract: float = 0.65  # a commonly-cited US options-broker rate; disclosed, not fitted
    slippage_pct_of_mid: float = 0.0  # extra, beyond the modeled bid/ask spread already in the quotes

    label: str = "BASE"


COST_BASE = CostAssumptions(commission_per_contract=0.65, slippage_pct_of_mid=0.0, label="BASE")
COST_LOW = CostAssumptions(commission_per_contract=0.0, slippage_pct_of_mid=0.0, label="LOW_COST")
COST_HIGH = CostAssumptions(commission_per_contract=1.00, slippage_pct_of_mid=0.02, label="HIGH_COST")


@dataclass(frozen=True, slots=True)
class TradeExecution:
    trade_id: str
    symbol: str
    strategy: str
    entry_date: date
    entry_price: float  # net debit(+)/credit(-) per share, BEFORE costs
    exit_date: date
    exit_price: float  # net payoff per share at exit (intrinsic value for expiration exits)
    quantity: int
    fees: float
    slippage: float
    gross_pnl: float
    net_pnl: float
    max_loss_defined: float  # the strategy's own defined max loss, for sanity-bounding
    mfe: float | None  # None when not computed (see module docstring)
    mae: float | None
    score: float = 0.0  # the TradeScoreBreakdown.total at entry — for score-calibration analysis (Phase J)


def _leg_entry_price(leg, cost: CostAssumptions) -> float:
    """BUY legs pay the (worse, realistic) ask; SELL legs receive the bid.
    This is a conservative, disclosed fill assumption — not mid-price."""
    base = leg.contract.ask if leg.side == "BUY" else leg.contract.bid
    slip = base * cost.slippage_pct_of_mid
    return base + slip if leg.side == "BUY" else base - slip


def _leg_intrinsic_at(leg, underlying_price: float) -> float:
    if leg.right == OptionRight.CALL:
        intrinsic = max(underlying_price - leg.contract.strike, 0.0)
    else:
        intrinsic = max(leg.contract.strike - underlying_price, 0.0)
    return intrinsic


def entry_to_expiration_pnl(
    candidate: TradeCandidate,
    entry_date: date,
    underlying_price_at_expiration: float,
    *,
    quantity: int = 1,
    cost: CostAssumptions = COST_BASE,
) -> TradeExecution:
    """Computes P&L leg-by-leg: net entry cost (sum of realistic fills,
    signed by side) vs. net exit value (sum of intrinsic payoffs, signed by
    side), times the contract multiplier and quantity, minus costs."""
    entry_net = sum(
        (_leg_entry_price(leg, cost) if leg.side == "BUY" else -_leg_entry_price(leg, cost))
        for leg in candidate.legs
    )
    exit_net = sum(
        (_leg_intrinsic_at(leg, underlying_price_at_expiration) if leg.side == "BUY"
         else -_leg_intrinsic_at(leg, underlying_price_at_expiration))
        for leg in candidate.legs
    )

    gross_pnl = (exit_net - entry_net) * CONTRACT_MULTIPLIER * quantity
    fees = cost.commission_per_contract * len(candidate.legs) * quantity * 2  # open + close
    net_pnl = gross_pnl - fees

    expiration = candidate.legs[0].contract.expiration if candidate.legs else entry_date

    return TradeExecution(
        trade_id=candidate.trade_id, symbol=candidate.symbol, strategy=candidate.strategy.value,
        entry_date=entry_date, entry_price=round(entry_net, 4),
        exit_date=expiration, exit_price=round(exit_net, 4),
        quantity=quantity, fees=round(fees, 2), slippage=0.0,
        gross_pnl=round(gross_pnl, 2), net_pnl=round(net_pnl, 2),
        max_loss_defined=candidate.max_loss, mfe=None, mae=None,
        score=candidate.score.total,
    )


def mark_to_market_path(
    candidate: TradeCandidate,
    dataset: HistoricalDataset,
    entry_date: date,
    exit_date: date,
    *,
    quantity: int = 1,
    cost: CostAssumptions = COST_BASE,
) -> tuple[float, float] | None:
    """Returns (mfe, mae) in dollars, or None if this dataset's provenance
    doesn't support daily repricing (see module docstring)."""
    if dataset.provenance != DataProvenance.SYNTHETIC_OPTIONS_DATA:
        return None

    from data.market.synthetic_source import RISK_FREE_RATE, _black_scholes, _trailing_realized_vol

    entry_net = sum(
        (_leg_entry_price(leg, cost) if leg.side == "BUY" else -_leg_entry_price(leg, cost))
        for leg in candidate.legs
    )

    closes_by_date = {d.as_of_date: d.underlying_close for d in dataset.days}
    all_dates = sorted(closes_by_date.keys())
    path_dates = [d for d in all_dates if entry_date <= d <= exit_date]
    if not path_dates:
        return None

    pnls = []
    for as_of in path_dates:
        idx = all_dates.index(as_of)
        trailing = [closes_by_date[d] for d in all_dates[: idx + 1]]
        spot = trailing[-1]
        vol = _trailing_realized_vol(trailing)

        mark_net = 0.0
        for leg in candidate.legs:
            dte = (leg.contract.expiration - as_of).days
            t_years = max(dte, 0) / 365.0
            price = _black_scholes(spot, leg.contract.strike, t_years, vol, leg.contract.right, RISK_FREE_RATE)
            mark_net += price if leg.side == "BUY" else -price

        pnl = (mark_net - entry_net) * CONTRACT_MULTIPLIER * quantity
        pnls.append(pnl)

    if not pnls:
        return None
    return max(pnls), min(pnls)
