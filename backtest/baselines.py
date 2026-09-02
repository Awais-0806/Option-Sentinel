"""Buy-and-hold underlying baseline (Day-4 Phase 10).

Deliberately outside the options/risk-sentinel machinery — this answers
a different question ("would you have been better off just holding
SPY?") using the same dataset and date range as the options backtests,
for an apples-to-apples reference point.
"""
from __future__ import annotations

from dataclasses import dataclass

from backtest.data_schema import HistoricalDataset


@dataclass(frozen=True, slots=True)
class BuyAndHoldResult:
    dataset_label: str
    start_date: str
    end_date: str
    start_price: float
    end_price: float
    shares: float
    starting_equity: float
    ending_equity: float
    total_pnl: float
    total_return_pct: float
    max_drawdown_pct: float


def run_buy_and_hold(dataset: HistoricalDataset, starting_equity: float = 100_000.0, warmup_days: int = 55) -> BuyAndHoldResult:
    days = dataset.days[warmup_days:]
    if not days:
        raise ValueError("not enough days after warmup to run a buy-and-hold baseline")

    start_price = days[0].underlying_close
    end_price = days[-1].underlying_close
    shares = starting_equity / start_price
    ending_equity = shares * end_price

    peak = starting_equity
    max_dd = 0.0
    for day in days:
        equity = shares * day.underlying_close
        peak = max(peak, equity)
        if peak > 0:
            max_dd = max(max_dd, (peak - equity) / peak)

    return BuyAndHoldResult(
        dataset_label=dataset.label(), start_date=days[0].as_of_date.isoformat(), end_date=days[-1].as_of_date.isoformat(),
        start_price=start_price, end_price=end_price, shares=round(shares, 4),
        starting_equity=starting_equity, ending_equity=round(ending_equity, 2),
        total_pnl=round(ending_equity - starting_equity, 2),
        total_return_pct=round((ending_equity - starting_equity) / starting_equity, 4),
        max_drawdown_pct=round(max_dd, 4),
    )
