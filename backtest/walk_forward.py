"""
Walk-forward backtest (Phase 9 fix).

Day-3 bug this replaces: the original train/validation split literally
sliced the HistoricalDataset in two, which meant the validation half
started with NO trailing history — the regime classifier was starving
for its first ~50 days of "validation," undermining the whole comparison.

Fix: run ONE continuous simulation across the entire dataset (decision
logic always has full, correct trailing history, exactly like production
would), and partition the resulting COMPLETED TRADES by which period
their entry date falls into, purely for reporting. Nothing about the
decision-making process changes at the period boundary — only which
bucket a completed trade's stats get counted into.

    WARM-UP  |  DEVELOPMENT  |  [GAP]  |  VALIDATION
    (indicator history only, trades here excluded from both period reports)
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum

from backtest.data_schema import HistoricalDataset
from backtest.pnl import TradeExecution
from backtest.runner import BacktestConfig, BacktestResult, run_backtest


class Period(str, Enum):
    WARMUP = "WARMUP"
    DEVELOPMENT = "DEVELOPMENT"
    GAP = "GAP"
    VALIDATION = "VALIDATION"


@dataclass(frozen=True, slots=True)
class WalkForwardPeriods:
    warmup_end: date          # inclusive: entries on/before this date are WARMUP
    development_end: date     # inclusive: entries after warmup_end through this date are DEVELOPMENT
    validation_start: date    # inclusive: entries on/after this date are VALIDATION; (development_end, validation_start) is GAP

    def classify(self, entry_date: date) -> Period:
        if entry_date <= self.warmup_end:
            return Period.WARMUP
        if entry_date <= self.development_end:
            return Period.DEVELOPMENT
        if entry_date < self.validation_start:
            return Period.GAP
        return Period.VALIDATION


@dataclass
class WalkForwardResult:
    full_result: BacktestResult  # the complete, continuous, undivided run (for leakage/reproducibility purposes)
    periods: WalkForwardPeriods
    development_trades: list[TradeExecution]
    validation_trades: list[TradeExecution]
    warmup_trade_count: int
    gap_trade_count: int
    insufficient_data_warning: str | None

    def development_stats(self) -> dict:
        return _stats_for(self.development_trades)

    def validation_stats(self) -> dict:
        return _stats_for(self.validation_trades)


def _stats_for(trades: list[TradeExecution]) -> dict:
    if not trades:
        return {"trade_count": 0, "note": "zero completed trades in this period"}
    pnls = sorted(t.net_pnl for t in trades)
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    n = len(pnls)
    median_pnl = pnls[n // 2] if n % 2 else (pnls[n // 2 - 1] + pnls[n // 2]) / 2
    gross_win, gross_loss = sum(wins), abs(sum(losses))
    return {
        "trade_count": n,
        "win_rate": round(len(wins) / n, 4),
        "avg_pnl": round(sum(pnls) / n, 2),
        "median_pnl": round(median_pnl, 2),
        "total_pnl": round(sum(pnls), 2),
        "profit_factor": round(gross_win / gross_loss, 4) if gross_loss > 0 else (float("inf") if gross_win > 0 else 0.0),
        "avg_winner": round(sum(wins) / len(wins), 2) if wins else None,
        "avg_loser": round(sum(losses) / len(losses), 2) if losses else None,
        "sample_size_warning": (
            "fewer than 10 trades — do not treat this as evidence of a robust edge either way"
            if n < 10 else None
        ),
    }


MIN_TRADES_FOR_ANY_CONCLUSION = 10


def run_walk_forward(dataset: HistoricalDataset, settings, config: BacktestConfig, periods: WalkForwardPeriods) -> WalkForwardResult:
    full_result = run_backtest(dataset, settings, config)

    dev_trades = [t for t in full_result.trades if periods.classify(t.entry_date) == Period.DEVELOPMENT]
    val_trades = [t for t in full_result.trades if periods.classify(t.entry_date) == Period.VALIDATION]
    warmup_trades = [t for t in full_result.trades if periods.classify(t.entry_date) == Period.WARMUP]
    gap_trades = [t for t in full_result.trades if periods.classify(t.entry_date) == Period.GAP]

    warning = None
    if len(dev_trades) < MIN_TRADES_FOR_ANY_CONCLUSION or len(val_trades) < MIN_TRADES_FOR_ANY_CONCLUSION:
        warning = (
            f"development has {len(dev_trades)} trades, validation has {len(val_trades)} trades — "
            f"below the {MIN_TRADES_FOR_ANY_CONCLUSION}-trade floor for treating either period's result "
            "as meaningful. Report both numbers, draw no conclusion from their comparison."
        )

    return WalkForwardResult(
        full_result=full_result, periods=periods,
        development_trades=dev_trades, validation_trades=val_trades,
        warmup_trade_count=len(warmup_trades), gap_trade_count=len(gap_trades),
        insufficient_data_warning=warning,
    )
