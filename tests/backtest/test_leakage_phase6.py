"""
Phase 6: four separately-named future-mutation tests, distinct from the
single combined mutation in test_replay_engine_leakage.py. Each isolates
ONE dimension of future data to prove that dimension specifically cannot
leak, rather than relying on one combined mutation to prove everything at
once.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta

from backtest.contract_universe import contracts_first_seen_dates, universe_as_of
from backtest.data_schema import HistoricalDataset
from backtest.replay_engine import decide_at
from core.config.settings import Settings
from data.market.synthetic_source import generate_synthetic_dataset
from risk.limits import PortfolioState


def _portfolio() -> PortfolioState:
    return PortfolioState(equity=100_000, buying_power=200_000, daily_pnl=0, peak_equity=100_000)


def _dataset() -> HistoricalDataset:
    return generate_synthetic_dataset("SPY", date(2025, 9, 1), date(2026, 3, 20))


def _mutate_future(dataset: HistoricalDataset, cutoff: date, mutator) -> HistoricalDataset:
    new_days = [mutator(day) if day.as_of_date > cutoff else day for day in dataset.days]
    return replace(dataset, days=tuple(new_days))


# ── 1. future-price mutation ────────────────────────────────────────────
def test_future_underlying_price_mutation_does_not_change_decision(settings):
    dataset = _dataset()
    target = dataset.days[100].as_of_date
    mutated = _mutate_future(dataset, target, lambda d: replace(d, underlying_close=d.underlying_close * 50))

    original = decide_at(dataset, target, _portfolio(), settings)
    after = decide_at(mutated, target, _portfolio(), settings)
    assert original.regime.regime == after.regime.regime
    assert original.regime.confidence == after.regime.confidence


# ── 2. future-option-bar (quote) mutation ───────────────────────────────
def test_future_option_bar_mutation_does_not_change_decision(settings):
    dataset = _dataset()
    target = dataset.days[100].as_of_date
    mutated = _mutate_future(
        dataset, target,
        lambda d: replace(d, contracts=tuple(replace(c, bid=0.01, ask=0.02) for c in d.contracts)),
    )

    original = decide_at(dataset, target, _portfolio(), settings)
    after = decide_at(mutated, target, _portfolio(), settings)
    orig_strategy = original.candidate.strategy if original.candidate else None
    mut_strategy = after.candidate.strategy if after.candidate else None
    assert orig_strategy == mut_strategy
    if original.candidate is not None:
        assert original.candidate.max_loss == after.candidate.max_loss


# ── 3. future-contract-universe mutation ────────────────────────────────
def test_future_contract_universe_mutation_does_not_change_decision(settings):
    """Adds entirely NEW contracts (never-before-seen strikes/expirations)
    on future days — a decision at T must not be affected by contracts
    that don't exist until later."""
    dataset = _dataset()
    target = dataset.days[100].as_of_date

    def add_phantom_contracts(day):
        from core.models.options import OptionContract, OptionRight
        phantom = OptionContract(
            symbol=f"PHANTOM_{day.as_of_date}", underlying="SPY",
            expiration=day.as_of_date + timedelta(days=999), strike=1.0,
            right=OptionRight.CALL, bid=0.01, ask=0.02, last=0.01, volume=1, open_interest=1,
        )
        return replace(day, contracts=day.contracts + (phantom,))

    mutated = _mutate_future(dataset, target, add_phantom_contracts)

    original = decide_at(dataset, target, _portfolio(), settings)
    after = decide_at(mutated, target, _portfolio(), settings)
    assert original.rejected_contract_count == after.rejected_contract_count
    orig_strategy = original.candidate.strategy if original.candidate else None
    mut_strategy = after.candidate.strategy if after.candidate else None
    assert orig_strategy == mut_strategy


def test_no_contract_is_visible_before_its_own_first_appearance():
    """Direct survivorship-bias check (Phase 5): universe_as_of(T) must
    never include a contract whose first-seen date is after T."""
    dataset = _dataset()
    first_seen = contracts_first_seen_dates(dataset)

    check_date = dataset.days[50].as_of_date
    universe = universe_as_of(dataset, check_date)
    for contract in universe:
        assert first_seen[contract.symbol] <= check_date, (
            f"{contract.symbol} appears in the universe on {check_date} but was first seen "
            f"on {first_seen[contract.symbol]} — future contract leaked backward"
        )


# ── 4. future-volume mutation ───────────────────────────────────────────
def test_future_volume_mutation_does_not_change_decision(settings):
    dataset = _dataset()
    target = dataset.days[100].as_of_date
    mutated = _mutate_future(
        dataset, target,
        lambda d: replace(d, contracts=tuple(replace(c, volume=999999, open_interest=999999) for c in d.contracts)),
    )

    original = decide_at(dataset, target, _portfolio(), settings)
    after = decide_at(mutated, target, _portfolio(), settings)
    assert original.rejected_contract_count == after.rejected_contract_count
    orig_strategy = original.candidate.strategy if original.candidate else None
    mut_strategy = after.candidate.strategy if after.candidate else None
    assert orig_strategy == mut_strategy


# ── Control: changing T itself changes at least one of these ───────────
def test_changing_the_decision_day_itself_is_permitted_to_change_the_decision():
    dataset = _dataset()
    target = dataset.days[100].as_of_date
    settings = Settings()

    def nuke_today(day):
        return replace(day, underlying_close=day.underlying_close * 50,
                        contracts=tuple(replace(c, bid=0.01, ask=0.02, volume=0, open_interest=0) for c in day.contracts))

    new_days = [nuke_today(d) if d.as_of_date == target else d for d in dataset.days]
    mutated = replace(dataset, days=tuple(new_days))

    original = decide_at(dataset, target, _portfolio(), settings)
    after = decide_at(mutated, target, _portfolio(), settings)
    assert (original.regime.features != after.regime.features
            or original.rejected_contract_count != after.rejected_contract_count)
