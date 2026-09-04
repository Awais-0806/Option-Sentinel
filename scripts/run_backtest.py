"""
Single-command, reproducible backtest experiment (Phase O / requirement #15).

Usage:
    python -m scripts.run_backtest --symbol SPY --start 2025-06-01 --end 2026-03-20 --data synthetic
    python -m scripts.run_backtest --symbol SPY --start 2025-11-01 --end 2026-01-15 --data csv --csv-path data/historical/SPY_2025-11-01_2026-01-15.csv

Given identical arguments and an identical (or absent, for --data synthetic)
input file, this produces byte-identical output — see
tests/backtest/test_reproducibility.py.

Prints a machine-readable JSON report to stdout AND writes it to
data/historical/backtest_report_<symbol>_<start>_<end>_<data>.json.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict

from backtest.baselines import run_buy_and_hold
from backtest.data_capability import gate_dataset_for_backtest
from backtest.pnl import COST_BASE, COST_HIGH, COST_LOW
from backtest.runner import BacktestConfig, run_backtest
from backtest.score_calibration import score_calibration_report
from core.config.settings import get_settings
from strategies.bear_put_spread import BearPutSpreadStrategy
from strategies.bull_call_spread import BullCallSpreadStrategy
from strategies.iron_condor import IronCondorStrategy


def _load_dataset(args):
    from datetime import datetime as _dt

    start = _dt.strptime(args.start, "%Y-%m-%d").date()
    end = _dt.strptime(args.end, "%Y-%m-%d").date()

    if args.data == "synthetic":
        from data.market.synthetic_source import generate_synthetic_dataset
        return generate_synthetic_dataset(args.symbol, start, end)
    if args.data == "csv":
        if not args.csv_path:
            print("ERROR: --csv-path is required when --data csv")
            sys.exit(1)
        from data.market.csv_source import load_csv_dataset
        return load_csv_dataset(args.csv_path, underlying=args.symbol)
    print(f"ERROR: unknown --data value {args.data!r} (expected 'synthetic' or 'csv')")
    sys.exit(1)


def main() -> int:
    parser = argparse.ArgumentParser(description="Reproducible OptionSentinel backtest experiment.")
    parser.add_argument("--symbol", default="SPY")
    parser.add_argument("--start", required=True, help="YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="YYYY-MM-DD")
    parser.add_argument("--data", choices=["synthetic", "csv"], default="synthetic")
    parser.add_argument("--csv-path", default=None)
    parser.add_argument("--warmup-days", type=int, default=55)
    parser.add_argument("--starting-equity", type=float, default=100_000.0)
    args = parser.parse_args()

    settings = get_settings()
    dataset = _load_dataset(args)

    capability = gate_dataset_for_backtest(dataset)
    print(f"Dataset: {dataset.label()}")
    print(f"Data capability: {capability.status.value}")
    for r in capability.reasons:
        print(f"  - {r}")
    print()

    configs = [
        BacktestConfig(name="OptionSentinel", warmup_days=args.warmup_days, starting_equity=args.starting_equity),
        BacktestConfig(name="Always Bull Call", forced_strategy=BullCallSpreadStrategy(),
                        warmup_days=args.warmup_days, starting_equity=args.starting_equity),
        BacktestConfig(name="Always Bear Put", forced_strategy=BearPutSpreadStrategy(),
                        warmup_days=args.warmup_days, starting_equity=args.starting_equity),
        BacktestConfig(name="Always Iron Condor", forced_strategy=IronCondorStrategy(),
                        warmup_days=args.warmup_days, starting_equity=args.starting_equity),
        BacktestConfig(name="Simple Regime Selector", skip_contract_validation=True,
                        warmup_days=args.warmup_days, starting_equity=args.starting_equity),
    ]

    report = {
        "dataset": dataset.label(),
        "dataset_provenance": dataset.provenance.value,
        "dataset_metadata": dataset.metadata,
        "data_capability": {"status": capability.status.value, "reasons": list(capability.reasons)},
        "configuration": {
            "symbol": args.symbol, "start": args.start, "end": args.end,
            "warmup_days": args.warmup_days, "starting_equity": args.starting_equity,
        },
        "risk_sentinel": "core risk.veto.RiskSentinel — identical class used by the live pipeline",
        "exit_model": "HOLD_TO_EXPIRATION (no early-exit rule implemented)",
        "buy_and_hold": asdict(
            run_buy_and_hold(
                dataset,
                starting_equity=args.starting_equity,
                warmup_days=args.warmup_days,
            )
        ),
        "strategies": {},
        "cost_sensitivity": {},
    }

    print("=== Buy and hold ===")
    print(json.dumps(report["buy_and_hold"], default=str, indent=2))

    for cfg in configs:
        result = run_backtest(dataset, settings, cfg)
        stats = result.stats()
        print(f"=== {cfg.name} ===")
        print(json.dumps(stats, default=str, indent=2))
        report["strategies"][cfg.name] = stats
        if cfg.name == "OptionSentinel" and result.trades:
            report["score_calibration"] = score_calibration_report(result.trades)

    print("\n=== Cost sensitivity (OptionSentinel) ===")
    for cost, label in [(COST_LOW, "OPTIMISTIC"), (COST_BASE, "BASE"), (COST_HIGH, "CONSERVATIVE")]:
        cfg = BacktestConfig(name="OptionSentinel", cost=cost, warmup_days=args.warmup_days, starting_equity=args.starting_equity)
        result = run_backtest(dataset, settings, cfg)
        stats = result.stats()
        print(f"{label}: total_pnl={stats.get('total_pnl')} profit_factor={stats.get('profit_factor')}")
        report["cost_sensitivity"][label] = stats

    out_path = f"data/historical/backtest_report_{args.symbol}_{args.start}_{args.end}_{args.data}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, default=str)
    print(f"\nFull report written to {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
