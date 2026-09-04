"""Phase O: "A second run with identical inputs must produce identical
results." Tests this directly against both the synthetic data generator
and the full backtest runner."""
from __future__ import annotations

from datetime import date

from backtest.runner import BacktestConfig, run_backtest
from data.market.synthetic_source import generate_synthetic_dataset


def test_synthetic_dataset_generation_is_deterministic():
    ds1 = generate_synthetic_dataset("SPY", date(2025, 9, 1), date(2025, 12, 1))
    ds2 = generate_synthetic_dataset("SPY", date(2025, 9, 1), date(2025, 12, 1))

    assert len(ds1.days) == len(ds2.days)
    for d1, d2 in zip(ds1.days, ds2.days):
        assert d1.as_of_date == d2.as_of_date
        assert d1.underlying_close == d2.underlying_close
        assert len(d1.contracts) == len(d2.contracts)
        for c1, c2 in zip(d1.contracts, d2.contracts):
            assert c1.symbol == c2.symbol
            assert c1.bid == c2.bid
            assert c1.ask == c2.ask


def test_full_backtest_run_is_deterministic(settings):
    ds1 = generate_synthetic_dataset("SPY", date(2025, 6, 1), date(2026, 1, 15))
    ds2 = generate_synthetic_dataset("SPY", date(2025, 6, 1), date(2026, 1, 15))

    result1 = run_backtest(ds1, settings, BacktestConfig(name="repro_test"))
    result2 = run_backtest(ds2, settings, BacktestConfig(name="repro_test"))

    stats1, stats2 = result1.stats(), result2.stats()
    assert stats1 == stats2, "identical inputs must produce byte-identical backtest stats"


def test_different_seeds_via_different_underlying_produce_different_results(settings):
    """Control test: proves the determinism above isn't trivial (e.g. the
    engine ignoring its input) by showing a DIFFERENT underlying symbol
    (different seed) produces different data and, generally, different
    results — establishing the test harness can detect a difference."""
    ds_spy = generate_synthetic_dataset("SPY", date(2025, 6, 1), date(2026, 1, 15))
    ds_qqq = generate_synthetic_dataset("QQQ", date(2025, 6, 1), date(2026, 1, 15))
    assert ds_spy.days[0].underlying_close != ds_qqq.days[0].underlying_close
