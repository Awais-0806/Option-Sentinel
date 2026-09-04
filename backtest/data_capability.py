"""
Data-availability gate (Day-3 follow-up requirement #12).

Before running a backtest against ANY dataset, check whether that
dataset's provenance/metadata actually supports the fidelity the backtest
claims. If not, return NOT_EVALUATABLE with an explicit reason rather
than silently running with a degraded assumption baked in invisibly.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from backtest.data_schema import DataProvenance, HistoricalDataset


class Evaluability(str, Enum):
    EVALUATABLE = "EVALUATABLE"
    EVALUATABLE_WITH_CAVEATS = "EVALUATABLE_WITH_CAVEATS"
    NOT_EVALUATABLE = "NOT_EVALUATABLE"


@dataclass(frozen=True, slots=True)
class CapabilityCheck:
    status: Evaluability
    reasons: tuple[str, ...]


def check_bid_ask_fidelity(dataset: HistoricalDataset) -> CapabilityCheck:
    """
    All four strategies (bull call, bear put, iron condor, long vol) price
    their entry/exit off bid/ask, so spread-cost realism directly depends
    on this. This is the single most important gate for this project,
    given the capability matrix finding that Alpaca's historical option
    bars do not carry bid/ask at all.
    """
    reasons: list[str] = []

    if dataset.provenance == DataProvenance.SYNTHETIC_OPTIONS_DATA:
        reasons.append(
            "bid/ask are model-generated (Black-Scholes fair value ± a fixed spread_pct "
            "assumption), not real quotes — fine for testing the DECISION LOGIC, not for "
            "trusting the resulting P&L as market-realistic."
        )
        return CapabilityCheck(Evaluability.EVALUATABLE_WITH_CAVEATS, tuple(reasons))

    if dataset.provenance == DataProvenance.REAL_USER_SUPPLIED_CSV:
        synthesized = dataset.metadata.get("bid_ask_synthesized_from_last_count", 0)
        total_rows = dataset.metadata.get("row_count", 0)
        if synthesized == 0:
            return CapabilityCheck(Evaluability.EVALUATABLE, ("dataset provides genuine bid/ask for every row",))
        if total_rows and synthesized == total_rows:
            return CapabilityCheck(
                Evaluability.NOT_EVALUATABLE,
                (
                    (
                        f"all {total_rows} rows have bid=ask=last (no real bid/ask present — "
                        "this is almost certainly output from scripts/fetch_historical_options.py's "
                        "get_option_bars() path, which the capability matrix confirms carries no "
                        "bid/ask). A spread-cost-aware backtest cannot be honestly run on this data."
                    ),
                ),
            )
        pct = synthesized / total_rows if total_rows else 1.0
        return CapabilityCheck(
            Evaluability.EVALUATABLE_WITH_CAVEATS,
            (f"{synthesized}/{total_rows} rows ({pct:.0%}) had bid/ask synthesized from last price, not real quotes",),
        )

    if dataset.provenance == DataProvenance.REAL_ALPACA_HISTORICAL:
        # Reserved for a future direct-API (non-CSV-roundtrip) ingestion path.
        # Per the capability matrix, this would need to come from a source
        # other than get_option_bars() to carry real bid/ask at all.
        reasons.append(
            "REAL_ALPACA_HISTORICAL provenance is used for datasets pulled directly via the "
            "adapter rather than round-tripped through a CSV — verify bid/ask presence explicitly "
            "before trusting this; the capability matrix shows Alpaca's historical bars endpoint "
            "does not carry bid/ask, so this provenance alone does not guarantee it."
        )
        return CapabilityCheck(Evaluability.EVALUATABLE_WITH_CAVEATS, tuple(reasons))

    return CapabilityCheck(Evaluability.NOT_EVALUATABLE, ("unrecognized dataset provenance",))


def check_strategy_requirements(dataset: HistoricalDataset, requires_iv_or_greeks: bool = False) -> CapabilityCheck:
    """This project's four strategies select strikes by moneyness, not by
    delta/IV, so requires_iv_or_greeks is False for all of them today —
    but the gate exists so that changes to strike-selection logic in the
    future (documented in docs/ARCHITECTURE.md) can't silently start
    depending on data this dataset doesn't have."""
    if not requires_iv_or_greeks:
        return CapabilityCheck(Evaluability.EVALUATABLE, ("strategy does not require IV/Greeks",))

    sample_contract = next((c for day in dataset.days for c in day.contracts), None)
    if sample_contract is None:
        return CapabilityCheck(Evaluability.NOT_EVALUATABLE, ("dataset has zero contracts",))
    if sample_contract.implied_volatility is None and sample_contract.delta is None:
        return CapabilityCheck(
            Evaluability.NOT_EVALUATABLE,
            (("strategy requires IV/Greeks but dataset carries neither — per the capability matrix, "
              "this is expected for any dataset built from Alpaca's historical bars endpoint"),),
        )
    return CapabilityCheck(Evaluability.EVALUATABLE, ("IV/Greeks present",))


def gate_dataset_for_backtest(dataset: HistoricalDataset, *, require_bid_ask: bool = True) -> CapabilityCheck:
    """The single entry point backtest/runner.py calls before starting."""
    checks = []
    if require_bid_ask:
        checks.append(check_bid_ask_fidelity(dataset))
    checks.append(check_strategy_requirements(dataset, requires_iv_or_greeks=False))

    if any(c.status == Evaluability.NOT_EVALUATABLE for c in checks):
        reasons = tuple(r for c in checks if c.status == Evaluability.NOT_EVALUATABLE for r in c.reasons)
        return CapabilityCheck(Evaluability.NOT_EVALUATABLE, reasons)
    if any(c.status == Evaluability.EVALUATABLE_WITH_CAVEATS for c in checks):
        reasons = tuple(r for c in checks for r in c.reasons)
        return CapabilityCheck(Evaluability.EVALUATABLE_WITH_CAVEATS, reasons)
    return CapabilityCheck(Evaluability.EVALUATABLE, tuple(r for c in checks for r in c.reasons))


# ── Per-strategy evaluability (Day-4 Phase 4) ──────────────────────────
# All four strategies currently select strikes by MONEYNESS (see
# strategies/*.py), not by delta/IV — so none of them structurally
# require IV or Greeks today. What they ALL require, identically, is
# usable bid/ask (their entry/exit debit-or-credit math is meaningless
# without it) and at least one listed expiration within their DTE window.
# This function is intentionally per-strategy (not just per-dataset) so
# that if a strategy's requirements diverge in the future, this is the
# one place that has to change.
STRATEGY_REQUIREMENTS: dict[str, dict] = {
    "BULL_CALL_SPREAD": {"requires_bid_ask": True, "requires_iv_or_greeks": False, "min_dte": 21, "max_dte": 45},
    "BEAR_PUT_SPREAD": {"requires_bid_ask": True, "requires_iv_or_greeks": False, "min_dte": 21, "max_dte": 45},
    "IRON_CONDOR": {"requires_bid_ask": True, "requires_iv_or_greeks": False, "min_dte": 21, "max_dte": 45},
    "LONG_VOLATILITY": {"requires_bid_ask": True, "requires_iv_or_greeks": False, "min_dte": 14, "max_dte": 35},
}


def check_expiration_coverage(dataset: HistoricalDataset, min_dte: int, max_dte: int) -> CapabilityCheck:
    """Does this dataset ever offer an expiration inside the strategy's DTE window,
    on any day? A dataset can pass bid/ask fidelity and still be useless for a
    strategy if it never actually lists a usable expiration."""
    for day in dataset.days:
        for c in day.contracts:
            dte = (c.expiration - day.as_of_date).days
            if min_dte <= dte <= max_dte:
                return CapabilityCheck(Evaluability.EVALUATABLE, (f"found a {dte}-DTE contract on {day.as_of_date}",))
    return CapabilityCheck(
        Evaluability.NOT_EVALUATABLE,
        (f"no contract in this dataset ever falls within the {min_dte}-{max_dte} DTE window",),
    )


def check_strategy_evaluability(dataset: HistoricalDataset, strategy_name: str) -> CapabilityCheck:
    """Returns EVALUATABLE / EVALUATABLE_WITH_CAVEATS / NOT_EVALUATABLE for
    ONE named strategy against ONE dataset, with machine-readable reasons —
    Day-4 Phase 4 requirement, distinct from the dataset-wide gate above."""
    if strategy_name not in STRATEGY_REQUIREMENTS:
        return CapabilityCheck(Evaluability.NOT_EVALUATABLE, (f"unknown strategy {strategy_name!r}",))
    req = STRATEGY_REQUIREMENTS[strategy_name]

    checks = []
    if req["requires_bid_ask"]:
        checks.append(check_bid_ask_fidelity(dataset))
    checks.append(check_strategy_requirements(dataset, requires_iv_or_greeks=req["requires_iv_or_greeks"]))
    checks.append(check_expiration_coverage(dataset, req["min_dte"], req["max_dte"]))

    if any(c.status == Evaluability.NOT_EVALUATABLE for c in checks):
        reasons = tuple(r for c in checks if c.status == Evaluability.NOT_EVALUATABLE for r in c.reasons)
        return CapabilityCheck(Evaluability.NOT_EVALUATABLE, reasons)
    if any(c.status == Evaluability.EVALUATABLE_WITH_CAVEATS for c in checks):
        return CapabilityCheck(Evaluability.EVALUATABLE_WITH_CAVEATS, tuple(r for c in checks for r in c.reasons))
    return CapabilityCheck(Evaluability.EVALUATABLE, tuple(r for c in checks for r in c.reasons))


def strategy_evaluability_report(dataset: HistoricalDataset) -> dict[str, dict]:
    return {
        name: {"status": check.status.value, "reasons": list(check.reasons)}
        for name, check in ((n, check_strategy_evaluability(dataset, n)) for n in STRATEGY_REQUIREMENTS)
    }
