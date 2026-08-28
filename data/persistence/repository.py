"""
Repository functions translate in-memory domain objects (dataclasses in
core/models) into persisted audit-trail rows. Keeping this translation
in one file means the ORM schema can evolve (e.g. SQLite -> Postgres per
the spec) without touching agent logic.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from core.models.market import MarketRegime
from core.models.risk import RiskDecision
from core.models.trade import TradeCandidate
from data.persistence.models import MarketScan, Opportunity, Order, RiskCheck, SystemEvent


def record_market_scan(session: Session, regime: MarketRegime) -> MarketScan:
    row = MarketScan(
        symbol=regime.symbol,
        regime=regime.regime.value,
        confidence=regime.confidence,
        features=regime.features,
    )
    session.add(row)
    session.flush()
    return row


def record_opportunity(session: Session, candidate: TradeCandidate, regime: MarketRegime) -> Opportunity:
    row = Opportunity(
        trade_id=candidate.trade_id,
        symbol=candidate.symbol,
        strategy=candidate.strategy.value,
        regime=regime.regime.value,
        score=candidate.score.total,
        size_tier=candidate.size_tier.value if candidate.size_tier else "NO_TRADE",
        rationale=candidate.rationale,
        max_profit=candidate.max_profit if candidate.max_profit != float("inf") else 1e12,
        max_loss=candidate.max_loss,
        probability_estimate=candidate.probability_estimate,
    )
    session.add(row)
    session.flush()
    return row


def record_risk_check(session: Session, opportunity_row: Opportunity, decision: RiskDecision) -> RiskCheck:
    row = RiskCheck(
        opportunity_id=opportunity_row.id,
        verdict=decision.verdict.value,
        approved_quantity=decision.approved_quantity,
        reasons=decision.to_dict()["reasons"],
    )
    session.add(row)
    session.flush()
    return row


def record_order(
    session: Session,
    opportunity_row: Opportunity,
    *,
    client_order_id: str,
    broker_order_id: str | None,
    status: str,
    quantity: int,
    filled_quantity: int,
    execution_mode: str,
) -> Order:
    row = Order(
        opportunity_id=opportunity_row.id,
        client_order_id=client_order_id,
        broker_order_id=broker_order_id,
        status=status,
        quantity=quantity,
        filled_quantity=filled_quantity,
        execution_mode=execution_mode,
    )
    session.add(row)
    session.flush()
    return row


def record_system_event(session: Session, event: str, level: str, detail: dict) -> SystemEvent:
    row = SystemEvent(event=event, level=level, detail=detail)
    session.add(row)
    session.flush()
    return row
