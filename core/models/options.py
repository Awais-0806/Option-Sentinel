from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum


class OptionRight(str, Enum):
    CALL = "CALL"
    PUT = "PUT"


@dataclass(frozen=True, slots=True)
class OptionContract:
    symbol: str                # OCC-style contract symbol
    underlying: str
    expiration: date
    strike: float
    right: OptionRight
    bid: float
    ask: float
    last: float | None
    volume: int
    open_interest: int
    implied_volatility: float | None = None
    delta: float | None = None
    gamma: float | None = None
    theta: float | None = None
    vega: float | None = None

    @property
    def mid(self) -> float:
        if self.bid <= 0 or self.ask <= 0:
            return 0.0
        return round((self.bid + self.ask) / 2, 4)

    @property
    def spread(self) -> float:
        return round(max(self.ask - self.bid, 0.0), 4)

    @property
    def spread_pct(self) -> float:
        """Spread as a fraction of mid price. Returns 1.0 (worst case) for unpriced/garbage quotes."""
        if self.mid <= 0:
            return 1.0
        return round(self.spread / self.mid, 4)

    @property
    def is_tradeable(self) -> bool:
        """Baseline sanity check — NOT the full liquidity gate (see risk/limits.py)."""
        return self.bid > 0 and self.ask > 0 and self.ask >= self.bid and self.volume >= 0


@dataclass(frozen=True, slots=True)
class OptionChainSlice:
    underlying: str
    fetched_at: str
    contracts: tuple[OptionContract, ...]

    def calls(self) -> list[OptionContract]:
        return [c for c in self.contracts if c.right == OptionRight.CALL]

    def puts(self) -> list[OptionContract]:
        return [c for c in self.contracts if c.right == OptionRight.PUT]

    def for_expiration(self, expiration: date) -> list[OptionContract]:
        return [c for c in self.contracts if c.expiration == expiration]
