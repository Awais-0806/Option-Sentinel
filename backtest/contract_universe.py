"""
Contract universe builder (Phase 5).

This module doesn't add new machinery — it makes an invariant that was
already implicit in the data model EXPLICIT and TESTED, per the Day-4
instruction: "For every evaluation date, identify contracts that were
actually available at that time. Avoid survivorship bias. Do not use
contracts that did not exist yet."

The invariant: `HistoricalDay.contracts` for day T contains ONLY
contracts that were part of T's own chain snapshot — never a contract
whose existence was only discovered on a later day. This is true by
construction in both data sources:
  - synthetic_source.py generates a fresh contract list every single day
    from that day's own strike/expiration grid — it never looks forward.
  - csv_source.py groups rows strictly by their own `date` column.

`universe_as_of()` below is the one function anything should call to get
"what contracts existed on this date" — it exists so that's a named,
testable operation rather than an implicit assumption buried in
replay_engine.py.
"""
from __future__ import annotations

from datetime import date

from backtest.data_schema import HistoricalDataset
from core.models.options import OptionContract


def universe_as_of(dataset: HistoricalDataset, as_of: date) -> tuple[OptionContract, ...]:
    """Returns exactly the contracts listed on `as_of`'s own day record —
    nothing pulled forward from a later day, nothing carried over from an
    earlier day (a contract that stops being listed is simply gone, which
    is itself realistic: it either expired or Alpaca/the data source
    stopped quoting it)."""
    day = next((d for d in dataset.days if d.as_of_date == as_of), None)
    return day.contracts if day is not None else ()


def contracts_first_seen_dates(dataset: HistoricalDataset) -> dict[str, date]:
    """For every contract symbol, the EARLIEST date it appears in the
    dataset. Used by the survivorship-bias regression test below to prove
    a contract is never usable before its own first appearance."""
    first_seen: dict[str, date] = {}
    for day in dataset.days:
        for c in day.contracts:
            if c.symbol not in first_seen or day.as_of_date < first_seen[c.symbol]:
                first_seen[c.symbol] = day.as_of_date
    return first_seen
