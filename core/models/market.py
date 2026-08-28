"""Market data & regime domain models.

Plain dataclasses (not pydantic) on purpose: these are the pure-logic core
used by the regime classifier and scoring engine, which should be testable
with zero external dependencies. Pydantic is used at the FastAPI boundary
(apps/api) where HTTP validation actually matters.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class RegimeLabel(str, Enum):
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    RANGE = "RANGE"
    HIGH_VOLATILITY = "HIGH_VOLATILITY"
    LOW_VOLATILITY = "LOW_VOLATILITY"
    UNCERTAIN = "UNCERTAIN"


@dataclass(frozen=True, slots=True)
class PriceBar:
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass(frozen=True, slots=True)
class MarketRegime:
    symbol: str
    regime: RegimeLabel
    confidence: float  # 0.0 - 1.0
    features: dict[str, float] = field(default_factory=dict)
    as_of: datetime | None = None

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "regime": self.regime.value,
            "confidence": round(self.confidence, 4),
            "features": {k: round(v, 6) for k, v in self.features.items()},
            "as_of": self.as_of.isoformat() if self.as_of else None,
        }
