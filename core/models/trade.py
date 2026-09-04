from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from .options import OptionContract, OptionRight


class TradeStrategy(str, Enum):
    BULL_CALL_SPREAD = "BULL_CALL_SPREAD"
    BEAR_PUT_SPREAD = "BEAR_PUT_SPREAD"
    IRON_CONDOR = "IRON_CONDOR"
    LONG_VOLATILITY = "LONG_VOLATILITY"


class SizeTier(str, Enum):
    NO_TRADE = "NO_TRADE"
    SMALL_SIZE = "SMALL_SIZE"
    NORMAL_SIZE = "NORMAL_SIZE"
    HIGH_CONVICTION_SIZE = "HIGH_CONVICTION_SIZE"


@dataclass(frozen=True, slots=True)
class TradeLeg:
    contract: OptionContract
    side: str          # "BUY" or "SELL"
    quantity: int = 1

    @property
    def right(self) -> OptionRight:
        return self.contract.right


@dataclass(frozen=True, slots=True)
class TradeScoreBreakdown:
    market_regime: float
    options_signal: float
    volatility_edge: float
    momentum: float
    liquidity: float
    risk_reward: float
    news_catalyst: float

    @property
    def total(self) -> float:
        return round(
            self.market_regime + self.options_signal + self.volatility_edge
            + self.momentum + self.liquidity + self.risk_reward + self.news_catalyst,
            2,
        )

    def to_dict(self) -> dict:
        d = {
            "market_regime": self.market_regime,
            "options_signal": self.options_signal,
            "volatility_edge": self.volatility_edge,
            "momentum": self.momentum,
            "liquidity": self.liquidity,
            "risk_reward": self.risk_reward,
            "news_catalyst": self.news_catalyst,
        }
        d["total"] = self.total
        return d


@dataclass(frozen=True, slots=True)
class TradeCandidate:
    trade_id: str
    symbol: str
    strategy: TradeStrategy
    legs: tuple[TradeLeg, ...]
    rationale: str
    max_profit: float
    max_loss: float
    breakeven: tuple[float, ...]
    probability_estimate: float | None
    score: TradeScoreBreakdown
    size_tier: SizeTier
    created_at: datetime


@dataclass(frozen=True, slots=True)
class TradeJournalEntry:
    """One row of the human- and machine-readable trade journal / audit trail."""
    trade_id: str
    timestamp: datetime
    symbol: str
    strategy: TradeStrategy
    regime: str
    score: float
    entry_debit_or_credit: float
    max_profit: float
    max_loss: float
    probability_estimate: float | None
    risk_decision: str
    risk_reasons: tuple[str, ...]
    order_id: str | None = None
    execution_status: str = "PENDING"
    exit_reason: str | None = None
    realized_pnl: float | None = None

    def to_dict(self) -> dict:
        return {
            "trade_id": self.trade_id,
            "timestamp": self.timestamp.isoformat(),
            "symbol": self.symbol,
            "strategy": self.strategy.value,
            "regime": self.regime,
            "score": self.score,
            "entry_debit_or_credit": self.entry_debit_or_credit,
            "max_profit": self.max_profit,
            "max_loss": self.max_loss,
            "probability_estimate": self.probability_estimate,
            "risk_decision": self.risk_decision,
            "risk_reasons": list(self.risk_reasons),
            "order_id": self.order_id,
            "execution_status": self.execution_status,
            "exit_reason": self.exit_reason,
            "realized_pnl": self.realized_pnl,
        }
