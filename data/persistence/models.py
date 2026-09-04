"""
SQLAlchemy ORM models — the audit trail (Milestone 9).

Every trade decision, approved or rejected, gets a row here. This is
what makes "Risk Sentinel rejected a 94-scored trade" a defensible,
demoable claim instead of a marketing line — judges can query it.
"""
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def _utcnow() -> datetime:
    return datetime.now(UTC)


class MarketScan(Base):
    __tablename__ = "market_scans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(16), index=True)
    regime: Mapped[str] = mapped_column(String(32))
    confidence: Mapped[float] = mapped_column(Float)
    features: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, index=True)


class Opportunity(Base):
    __tablename__ = "opportunities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    trade_id: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    symbol: Mapped[str] = mapped_column(String(16), index=True)
    strategy: Mapped[str] = mapped_column(String(32))
    regime: Mapped[str] = mapped_column(String(32))
    score: Mapped[float] = mapped_column(Float)
    size_tier: Mapped[str] = mapped_column(String(32))
    rationale: Mapped[str] = mapped_column(Text)
    max_profit: Mapped[float] = mapped_column(Float)
    max_loss: Mapped[float] = mapped_column(Float)
    probability_estimate: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, index=True)

    risk_checks: Mapped[list[RiskCheck]] = relationship(back_populates="opportunity")
    orders: Mapped[list[Order]] = relationship(back_populates="opportunity")


class RiskCheck(Base):
    __tablename__ = "risk_checks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    opportunity_id: Mapped[int] = mapped_column(ForeignKey("opportunities.id"), index=True)
    verdict: Mapped[str] = mapped_column(String(32))
    approved_quantity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reasons: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, index=True)

    opportunity: Mapped[Opportunity] = relationship(back_populates="risk_checks")


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    opportunity_id: Mapped[int] = mapped_column(ForeignKey("opportunities.id"), index=True)
    client_order_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    broker_order_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(32))
    quantity: Mapped[int] = mapped_column(Integer)
    filled_quantity: Mapped[int] = mapped_column(Integer, default=0)
    execution_mode: Mapped[str] = mapped_column(String(32))
    # DRY_RUN | PAPER_SIMULATION | PAPER_MANUAL_APPROVAL | PAPER_AUTONOMOUS | LIVE (blocked)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, index=True)

    opportunity: Mapped[Opportunity] = relationship(back_populates="orders")


class Position(Base):
    __tablename__ = "positions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    trade_id: Mapped[str] = mapped_column(String(32), index=True)
    symbol: Mapped[str] = mapped_column(String(16), index=True)
    strategy: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16), default="OPEN")  # OPEN | CLOSED
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    exit_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    realized_pnl: Mapped[float | None] = mapped_column(Float, nullable=True)


class PnLSnapshot(Base):
    __tablename__ = "pnl_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    equity: Mapped[float] = mapped_column(Float)
    daily_pnl: Mapped[float] = mapped_column(Float)
    total_pnl: Mapped[float] = mapped_column(Float)
    drawdown_pct: Mapped[float] = mapped_column(Float)
    open_positions: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, index=True)


class SystemEvent(Base):
    __tablename__ = "system_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event: Mapped[str] = mapped_column(String(64), index=True)
    level: Mapped[str] = mapped_column(String(16))
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, index=True)
