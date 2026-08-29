"""
Phase F requirement, verbatim from the spec: "If data at T+1 is changed,
the decision at T must not change. Add a regression test proving this."

This file proves it two ways:
1. Mutating every day AFTER the decision date -> decision is byte-identical.
2. Mutating the decision date ITSELF (a control) -> decision DOES change,
   proving test #1 isn't vacuously true because decide_at() ignores all
   its input.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import date

from backtest.data_schema import HistoricalDataset
from backtest.replay_engine import decide_at
from core.config.settings import Settings
from core.models.options import OptionRight
from data.market.synthetic_source import generate_synthetic_dataset
from risk.limits import PortfolioState


def _portfolio() -> PortfolioState:
    return PortfolioState(equity=100_000, buying_power=200_000, daily_pnl=0, peak_equity=100_000)


def _mutate_days_after(dataset: HistoricalDataset, cutoff: date) -> HistoricalDataset:
    """Replaces every contract on every day AFTER cutoff with wildly
    different, deliberately extreme values — if decide_at(cutoff) is
    leakage-safe, none of this should be visible to it."""
    new_days = []
    for day in dataset.days:
        if day.as_of_date <= cutoff:
            new_days.append(day)
            continue
        mutated_contracts = tuple(
            replace(c, bid=9999.0, ask=9999.5, volume=999999, open_interest=999999, implied_volatility=5.0)
            for c in day.contracts
        )
        new_days.append(replace(day, underlying_close=day.underlying_close * 1000, contracts=mutated_contracts))
    return replace(dataset, days=tuple(new_days))


def _mutate_day_itself(dataset: HistoricalDataset, target: date) -> HistoricalDataset:
    """Control mutation: changes ONLY the target day, to prove the test
    harness can actually detect a changed decision when one should occur."""
    new_days = []
    for day in dataset.days:
        if day.as_of_date != target:
            new_days.append(day)
            continue
        mutated_contracts = tuple(
            replace(c, bid=9999.0, ask=9999.5, volume=999999, open_interest=999999, implied_volatility=5.0)
            for c in day.contracts
        )
        new_days.append(replace(day, underlying_close=day.underlying_close * 1000, contracts=mutated_contracts))
    return replace(dataset, days=tuple(new_days))


def test_mutating_future_days_does_not_change_the_decision_at_t(settings):
    dataset = generate_synthetic_dataset("SPY", date(2025, 9, 1), date(2026, 3, 20))
    target = dataset.days[100].as_of_date
    portfolio = _portfolio()

    original = decide_at(dataset, target, portfolio, settings)
    mutated_future = _mutate_days_after(dataset, target)
    after_mutation = decide_at(mutated_future, target, portfolio, settings)

    assert original.regime.regime == after_mutation.regime.regime
    assert original.regime.confidence == after_mutation.regime.confidence
    assert original.regime.features == after_mutation.regime.features
    assert original.rejected_contract_count == after_mutation.rejected_contract_count

    orig_strategy = original.candidate.strategy if original.candidate else None
    mut_strategy = after_mutation.candidate.strategy if after_mutation.candidate else None
    assert orig_strategy == mut_strategy

    if original.candidate is not None:
        assert original.candidate.score.total == after_mutation.candidate.score.total
        assert original.candidate.max_loss == after_mutation.candidate.max_loss
        assert original.candidate.max_profit == after_mutation.candidate.max_profit

    orig_verdict = original.risk_decision.verdict if original.risk_decision else None
    mut_verdict = after_mutation.risk_decision.verdict if after_mutation.risk_decision else None
    assert orig_verdict == mut_verdict


def test_mutating_the_decision_day_itself_does_change_the_decision_control(settings):
    """Control test: if this ever fails, the leakage test above is
    meaningless (it would mean decide_at ignores its input entirely)."""
    dataset = generate_synthetic_dataset("SPY", date(2025, 9, 1), date(2026, 3, 20))
    target = dataset.days[100].as_of_date
    portfolio = _portfolio()

    original = decide_at(dataset, target, portfolio, settings)
    mutated_today = _mutate_day_itself(dataset, target)
    after_mutation = decide_at(mutated_today, target, portfolio, settings)

    # Extreme spread/price/OI mutation on the decision day itself must change
    # at least ONE of: regime features (underlying_close changed 1000x) or
    # which/whether contracts pass the validator (spread went from ~4% to
    # ~0.005%, OI/volume changed by orders of magnitude).
    changed = (
        original.regime.features != after_mutation.regime.features
        or original.rejected_contract_count != after_mutation.rejected_contract_count
    )
    assert changed, "mutating the decision day itself should visibly change something — if not, the test harness can't detect real leakage either"


def test_truncated_dataset_view_never_contains_future_days():
    """Direct unit test of the primitive the leakage guarantee is built on."""
    dataset = generate_synthetic_dataset("SPY", date(2025, 9, 1), date(2025, 10, 1))
    cutoff = dataset.days[5].as_of_date
    visible = dataset.as_of_or_earlier(cutoff)
    assert all(d.as_of_date <= cutoff for d in visible.days)
    assert len(visible.days) == 6  # days[0..5] inclusive
