"""
Data capability audit report (Day-4 Phase 3).

Produces the exact field-presence table requested, plus per-strategy
evaluability, as both a .json (machine-readable) and .md (human-readable)
file. Never fills an unavailable field with an invented value — "Present"
is computed by actually sampling the dataset, not assumed.
"""
from __future__ import annotations

import json
from pathlib import Path

from backtest.data_capability import strategy_evaluability_report
from backtest.data_schema import HistoricalDataset

FIELDS = [
    "timestamp", "symbol", "strike", "expiration", "call_put",
    "open", "high", "low", "close", "volume",
    "bid", "ask", "iv", "delta", "gamma", "theta", "vega", "open_interest",
]


def _sample_contracts(dataset: HistoricalDataset, n: int = 500):
    out = []
    for day in dataset.days:
        for c in day.contracts:
            out.append((day, c))
            if len(out) >= n:
                return out
    return out


def _field_stats(dataset: HistoricalDataset, field: str) -> dict:
    sample = _sample_contracts(dataset)
    if not sample:
        return {"present": False, "completeness": 0.0, "usable": False}

    def get(day, c):
        return {
            "timestamp": day.as_of_date, "symbol": c.underlying, "strike": c.strike,
            "expiration": c.expiration, "call_put": c.right.value,
            "open": day.underlying_close, "high": day.underlying_close, "low": day.underlying_close,
            "close": day.underlying_close, "volume": c.volume,
            "bid": c.bid, "ask": c.ask, "iv": c.implied_volatility,
            "delta": c.delta, "gamma": c.gamma, "theta": c.theta, "vega": c.vega,
            "open_interest": c.open_interest,
        }[field]

    values = [get(day, c) for day, c in sample]
    non_null = [v for v in values if v is not None]
    completeness = len(non_null) / len(values) if values else 0.0

    # "usable" is stricter than "present": a bid/ask column full of zeros
    # or a synthesized-from-last flag counts as present-but-not-genuinely-usable.
    usable = completeness > 0.99
    if field in ("bid", "ask") and dataset.metadata.get("bid_ask_synthesized_from_last_count", 0) > 0:
        usable = False

    return {"present": completeness > 0, "completeness": round(completeness, 4), "usable": usable}


def build_capability_report(dataset: HistoricalDataset) -> dict:
    field_table = {field: _field_stats(dataset, field) for field in FIELDS}
    return {
        "dataset_label": dataset.label(),
        "provenance": dataset.provenance.value,
        "date_range": [dataset.start_date.isoformat() if dataset.start_date else None,
                        dataset.end_date.isoformat() if dataset.end_date else None],
        "day_count": len(dataset.days),
        "metadata": dataset.metadata,
        "fields": field_table,
        "strategy_evaluability": strategy_evaluability_report(dataset),
    }


def write_capability_report(dataset: HistoricalDataset, out_dir: str = "data/historical") -> tuple[str, str]:
    report = build_capability_report(dataset)
    Path(out_dir).mkdir(parents=True, exist_ok=True)

    json_path = f"{out_dir}/data_capability_report.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, default=str)

    md_lines = [
        f"# Data Capability Report — {report['dataset_label']}", "",
        f"- Provenance: **{report['provenance']}**",
        f"- Date range: {report['date_range'][0]} to {report['date_range'][1]} ({report['day_count']} days)",
        "", "## Field availability", "",
        "| Field | Present | Completeness | Usable |", "|---|---|---|---|",
    ]
    for field in FIELDS:
        stats = report["fields"][field]
        md_lines.append(f"| {field} | {'✅' if stats['present'] else '❌'} | {stats['completeness']:.1%} | {'✅' if stats['usable'] else '❌'} |")

    md_lines += ["", "## Strategy evaluability", "", "| Strategy | Status | Reasons |", "|---|---|---|"]
    for name, info in report["strategy_evaluability"].items():
        reasons = "; ".join(info["reasons"])
        md_lines.append(f"| {name} | {info['status']} | {reasons} |")

    md_path = f"{out_dir}/data_capability_report.md"
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(md_lines) + "\n")

    return json_path, md_path
