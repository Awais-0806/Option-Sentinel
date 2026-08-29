"""
Score calibration (Phase J / requirement #11).

"The result may prove that the score works — or does not. Either result
is acceptable." This module only reports; it never asserts the score is
predictive.
"""
from __future__ import annotations

from backtest.pnl import TradeExecution

BUCKETS = [(90, 100), (80, 89.999), (70, 79.999), (60, 69.999), (0, 59.999)]
BUCKET_LABELS = ["90-100", "80-89", "70-79", "60-69", "<60"]


def score_calibration_report(trades: list[TradeExecution]) -> dict:
    buckets: dict[str, list[TradeExecution]] = {label: [] for label in BUCKET_LABELS}
    for trade in trades:
        for (lo, hi), label in zip(BUCKETS, BUCKET_LABELS):
            if lo <= trade.score <= hi:
                buckets[label].append(trade)
                break

    report = {}
    for label in BUCKET_LABELS:
        bucket_trades = buckets[label]
        if not bucket_trades:
            report[label] = {"trade_count": 0, "note": "no trades in this score range in this dataset"}
            continue
        wins = [t for t in bucket_trades if t.net_pnl > 0]
        pnls = [t.net_pnl for t in bucket_trades]
        report[label] = {
            "trade_count": len(bucket_trades),
            "win_rate": round(len(wins) / len(bucket_trades), 4),
            "avg_pnl": round(sum(pnls) / len(pnls), 2),
            "total_pnl": round(sum(pnls), 2),
        }

    non_empty = [(label, report[label]) for label in BUCKET_LABELS if report[label]["trade_count"] > 0]
    if len(non_empty) < 2:
        report["_interpretation"] = (
            "fewer than 2 non-empty score buckets in this dataset — no meaningful calibration "
            "conclusion can be drawn; do not interpret this as either confirming or refuting the scorer"
        )
    else:
        win_rates = [b["win_rate"] for _, b in non_empty]
        monotonic = all(win_rates[i] >= win_rates[i + 1] for i in range(len(win_rates) - 1))
        summary = ", ".join(f"{label}={bucket['win_rate']:.0%}" for label, bucket in non_empty)
        report["_interpretation"] = (
            f"win rate {'decreases' if monotonic else 'does NOT decrease'} monotonically "
            f"from high-score to low-score buckets in this sample ({summary}). "
            "This is descriptive only — sample sizes per bucket are small; do not treat this as "
            "statistical proof the score is or isn't predictive."
        )
    return report
