"""
Risk Sentinel — rule definitions (Agent 5, Milestone 7).

Design invariant: nothing in this file calls an LLM. Every rule here is a
pure function of numeric portfolio/trade state. This is what lets us say
in the write-up "the Risk Sentinel has final veto power and is fully
deterministic" and mean it.

RiskRule -> a single named check. RiskPolicy -> an ordered collection of
RiskRules. RiskSentinel (veto.py) evaluates a RiskPolicy against a
TradeRiskRequest and produces one RiskDecision.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Protocol

from core.config.settings import Settings
from core.models.options import OptionContract
from core.models.risk import RiskReason
from core.models.trade import TradeCandidate


@dataclass(frozen=True, slots=True)
class OpenPosition:
    trade_id: str
    symbol: str
    strategy: str
    risk_capital: float          # capital actually at risk (max_loss) for this position
    opened_at: datetime


@dataclass(frozen=True, slots=True)
class PortfolioState:
    """Snapshot of account/portfolio state at decision time — sourced from the
    Alpaca adapter (or a paper/mock adapter in DRY_RUN)."""
    equity: float
    buying_power: float
    daily_pnl: float
    peak_equity: float                    # for drawdown calc
    open_positions: tuple[OpenPosition, ...] = field(default_factory=tuple)
    recent_client_order_ids: tuple[str, ...] = field(default_factory=tuple)
    last_quote_timestamp: dict[str, datetime] = field(default_factory=dict)
    consecutive_risk_rejections: int = 0
    market_data_is_stale: bool = False
    abnormal_market_flag: bool = False    # e.g. circuit breaker halt, extreme index move

    @property
    def current_drawdown_pct(self) -> float:
        if self.peak_equity <= 0:
            return 0.0
        return max(0.0, (self.peak_equity - self.equity) / self.peak_equity)

    @property
    def total_open_risk_capital(self) -> float:
        return sum(p.risk_capital for p in self.open_positions)


@dataclass(frozen=True, slots=True)
class TradeRiskRequest:
    """Everything the Risk Sentinel needs to evaluate one candidate trade."""
    candidate: TradeCandidate
    portfolio: PortfolioState
    proposed_quantity: int
    client_order_id: str
    now: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class RiskRule(Protocol):
    name: str

    def evaluate(self, req: TradeRiskRequest, settings: Settings) -> RiskReason:
        ...


def _reason(name: str, passed: bool, detail: str) -> RiskReason:
    return RiskReason(rule=name, passed=passed, detail=detail)


# ── Individual rules ──────────────────────────────────────────────────────

def rule_max_trade_risk(req: TradeRiskRequest, settings: Settings) -> RiskReason:
    trade_risk = abs(req.candidate.max_loss) * req.proposed_quantity
    limit = req.portfolio.equity * settings.max_trade_risk_pct
    passed = trade_risk <= limit
    return _reason(
        "max_trade_risk",
        passed,
        f"trade_risk=${trade_risk:,.2f} limit=${limit:,.2f} "
        f"({settings.max_trade_risk_pct:.1%} of equity)",
    )


def rule_max_portfolio_risk(req: TradeRiskRequest, settings: Settings) -> RiskReason:
    prospective = req.portfolio.total_open_risk_capital + abs(req.candidate.max_loss) * req.proposed_quantity
    limit = req.portfolio.equity * settings.max_portfolio_risk_pct
    passed = prospective <= limit
    return _reason(
        "max_portfolio_risk",
        passed,
        f"prospective_total_risk=${prospective:,.2f} limit=${limit:,.2f} "
        f"({settings.max_portfolio_risk_pct:.1%} of equity)",
    )


def rule_max_daily_loss(req: TradeRiskRequest, settings: Settings) -> RiskReason:
    limit = -abs(req.portfolio.equity * settings.max_daily_loss_pct)
    passed = req.portfolio.daily_pnl > limit
    return _reason(
        "max_daily_loss",
        passed,
        f"daily_pnl=${req.portfolio.daily_pnl:,.2f} floor=${limit:,.2f}",
    )


def rule_max_drawdown(req: TradeRiskRequest, settings: Settings) -> RiskReason:
    dd = req.portfolio.current_drawdown_pct
    passed = dd <= settings.max_drawdown_pct
    return _reason(
        "max_drawdown",
        passed,
        f"current_drawdown={dd:.2%} limit={settings.max_drawdown_pct:.2%}",
    )


def rule_buying_power(req: TradeRiskRequest, settings: Settings) -> RiskReason:
    required = abs(req.candidate.max_loss) * req.proposed_quantity
    passed = req.portfolio.buying_power >= required
    return _reason(
        "buying_power",
        passed,
        f"required=${required:,.2f} available=${req.portfolio.buying_power:,.2f}",
    )


def rule_position_concentration(req: TradeRiskRequest, settings: Settings) -> RiskReason:
    same_symbol_risk = sum(
        p.risk_capital for p in req.portfolio.open_positions if p.symbol == req.candidate.symbol
    )
    prospective = same_symbol_risk + abs(req.candidate.max_loss) * req.proposed_quantity
    limit = req.portfolio.equity * settings.max_position_concentration_pct
    passed = prospective <= limit
    return _reason(
        "position_concentration",
        passed,
        f"symbol={req.candidate.symbol} prospective_symbol_risk=${prospective:,.2f} "
        f"limit=${limit:,.2f}",
    )


def rule_max_open_positions(req: TradeRiskRequest, settings: Settings) -> RiskReason:
    passed = len(req.portfolio.open_positions) < settings.max_open_positions
    return _reason(
        "max_open_positions",
        passed,
        f"open={len(req.portfolio.open_positions)} limit={settings.max_open_positions}",
    )


def rule_liquidity_spread(req: TradeRiskRequest, settings: Settings) -> RiskReason:
    bad_legs = [
        leg.contract.symbol
        for leg in req.candidate.legs
        if leg.contract.spread_pct > settings.max_bid_ask_spread_pct
        or leg.contract.open_interest < settings.min_open_interest
        or leg.contract.volume < settings.min_option_volume
    ]
    passed = len(bad_legs) == 0
    return _reason(
        "liquidity_spread",
        passed,
        "all legs within liquidity limits" if passed else f"illiquid legs: {bad_legs}",
    )


def rule_contract_sanity(req: TradeRiskRequest, settings: Settings) -> RiskReason:
    bad: list[str] = []
    for leg in req.candidate.legs:
        c: OptionContract = leg.contract
        if not c.is_tradeable:
            bad.append(f"{c.symbol}:bad_quote")
        if c.expiration < req.now.date():
            bad.append(f"{c.symbol}:expired")
    passed = len(bad) == 0
    return _reason("contract_sanity", passed, "ok" if passed else f"issues: {bad}")


def rule_stale_data(req: TradeRiskRequest, settings: Settings) -> RiskReason:
    passed = not req.portfolio.market_data_is_stale
    return _reason(
        "stale_data",
        passed,
        "market data fresh" if passed else "market data flagged stale — refusing to size a trade on it",
    )


def rule_duplicate_order(req: TradeRiskRequest, settings: Settings) -> RiskReason:
    passed = req.client_order_id not in req.portfolio.recent_client_order_ids
    return _reason(
        "duplicate_order",
        passed,
        "client_order_id unused" if passed else f"client_order_id {req.client_order_id} already submitted",
    )


def rule_abnormal_market(req: TradeRiskRequest, settings: Settings) -> RiskReason:
    passed = not req.portfolio.abnormal_market_flag
    return _reason(
        "abnormal_market",
        passed,
        "normal conditions" if passed else "abnormal market conditions flagged — new entries blocked",
    )


def rule_order_size_sane(req: TradeRiskRequest, settings: Settings) -> RiskReason:
    passed = 0 < req.proposed_quantity <= 50  # hard ceiling; contracts, not shares
    return _reason(
        "order_size_sane",
        passed,
        f"proposed_quantity={req.proposed_quantity}",
    )


DEFAULT_RULES: tuple[Callable[[TradeRiskRequest, Settings], RiskReason], ...] = (
    rule_stale_data,
    rule_abnormal_market,
    rule_contract_sanity,
    rule_liquidity_spread,
    rule_duplicate_order,
    rule_order_size_sane,
    rule_buying_power,
    rule_max_trade_risk,
    rule_max_portfolio_risk,
    rule_position_concentration,
    rule_max_open_positions,
    rule_max_daily_loss,
    rule_max_drawdown,
)


@dataclass(frozen=True, slots=True)
class RiskPolicy:
    """An ordered, named bundle of rules. Lets us have a stricter
    'competition day' policy vs a looser 'dev' policy without branching
    logic inside the sentinel itself."""
    name: str
    rules: tuple[Callable[[TradeRiskRequest, Settings], RiskReason], ...] = DEFAULT_RULES
