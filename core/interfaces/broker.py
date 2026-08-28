"""
BrokerAdapter — the one interface the entire trading engine depends on.

Per the spec's architecture requirement: "Do not hardwire Alpaca-specific
code into every module. Create an adapter/interface layer." Agents and
the orchestration pipeline import ONLY this Protocol. Concrete
implementations live in integrations/:

  integrations/alpaca/adapter.py        -> real Alpaca paper/live REST calls
  integrations/alpaca/mock_adapter.py   -> deterministic synthetic data,
                                            used for DRY_RUN and tests when
                                            no credentials/network are available

This means the same pipeline code runs identically whether it's plugged
into a live paper account or a mock for offline development.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol

from core.models.market import PriceBar
from core.models.options import OptionChainSlice


@dataclass(frozen=True, slots=True)
class AccountSnapshot:
    equity: float
    buying_power: float
    cash: float
    daily_pnl: float
    peak_equity: float
    is_paper: bool


@dataclass(frozen=True, slots=True)
class BrokerPosition:
    symbol: str
    strategy_hint: str | None
    quantity: int
    market_value: float
    unrealized_pl: float


@dataclass(frozen=True, slots=True)
class OrderResult:
    order_id: str
    client_order_id: str
    status: str  # e.g. "accepted", "filled", "partially_filled", "rejected"
    filled_qty: int
    submitted_at: datetime
    raw: dict | None = None


class BrokerAdapter(Protocol):
    """Every method an agent needs from a broker. Nothing more."""

    def get_account(self) -> AccountSnapshot: ...

    def get_positions(self) -> list[BrokerPosition]: ...

    def get_price_bars(self, symbol: str, lookback_days: int) -> list[PriceBar]: ...

    def get_option_chain(self, symbol: str, min_dte: int, max_dte: int) -> OptionChainSlice: ...

    def submit_order(
        self,
        *,
        legs: list,
        quantity: int,
        client_order_id: str,
        limit_price: float | None,
    ) -> OrderResult: ...

    def is_market_data_stale(self, symbol: str, max_age_seconds: int) -> bool: ...

    def health_check(self) -> dict[str, str]:
        """Returns a dict of subsystem -> status string (e.g. 'OK', 'FAIL: <reason>')."""
        ...
