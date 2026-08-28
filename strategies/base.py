from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date, datetime, timezone

from core.config.settings import Settings
from core.models.market import MarketRegime
from core.models.options import OptionChainSlice, OptionContract
from core.models.trade import TradeCandidate, TradeStrategy


@dataclass(frozen=True, slots=True)
class StrategyContext:
    symbol: str
    underlying_price: float
    regime: MarketRegime
    chain: OptionChainSlice
    settings: Settings
    now: datetime = None  # type: ignore[assignment]

    def __post_init__(self):
        if self.now is None:
            object.__setattr__(self, "now", datetime.now(timezone.utc))


def new_trade_id() -> str:
    return f"trd_{uuid.uuid4().hex[:12]}"


def nearest_expiration(chain: OptionChainSlice, min_dte: int, max_dte: int, today: date) -> date | None:
    candidates = sorted({c.expiration for c in chain.contracts})
    in_window = [e for e in candidates if min_dte <= (e - today).days <= max_dte]
    if not in_window:
        return None
    target_dte = (min_dte + max_dte) / 2
    return min(in_window, key=lambda e: abs((e - today).days - target_dte))


def closest_strike(contracts: list[OptionContract], target: float) -> OptionContract | None:
    if not contracts:
        return None
    return min(contracts, key=lambda c: abs(c.strike - target))


class Strategy(ABC):
    strategy_id: TradeStrategy

    @abstractmethod
    def evaluate(self, ctx: StrategyContext) -> bool:
        """Is this strategy even eligible given the current regime/context?"""

    @abstractmethod
    def build_trade(self, ctx: StrategyContext) -> TradeCandidate | None:
        """Construct a concrete TradeCandidate, or None if no valid contracts exist."""

    @abstractmethod
    def validate(self, ctx: StrategyContext, candidate: TradeCandidate) -> tuple[bool, list[str]]:
        """Strategy-specific structural sanity checks (independent of the Risk Sentinel)."""

    def _base_validate_legs(self, candidate: TradeCandidate) -> list[str]:
        problems: list[str] = []
        expirations = {leg.contract.expiration for leg in candidate.legs}
        if len(expirations) != 1:
            problems.append("legs span multiple expirations")
        for leg in candidate.legs:
            if not leg.contract.is_tradeable:
                problems.append(f"leg {leg.contract.symbol} has an unusable quote")
        return problems
