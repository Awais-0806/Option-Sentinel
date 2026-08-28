from __future__ import annotations

from datetime import date, datetime, timezone

from core.models.options import OptionContract, OptionRight
from core.models.trade import SizeTier, TradeCandidate, TradeLeg, TradeScoreBreakdown, TradeStrategy


def make_option(
    strike: float,
    right: OptionRight,
    bid: float,
    ask: float,
    *,
    expiration: date = date(2026, 10, 1),
    volume: int = 100,
    open_interest: int = 500,
    symbol: str | None = None,
) -> OptionContract:
    return OptionContract(
        symbol=symbol or f"TEST_{strike}_{right.value}",
        underlying="TEST",
        expiration=expiration,
        strike=strike,
        right=right,
        bid=bid,
        ask=ask,
        last=(bid + ask) / 2,
        volume=volume,
        open_interest=open_interest,
        implied_volatility=0.25,
        delta=0.5 if right == OptionRight.CALL else -0.5,
    )


def make_bull_call_candidate(max_loss: float = 500.0, max_profit: float = 1000.0) -> TradeCandidate:
    long_leg = make_option(400, OptionRight.CALL, 5.0, 5.2)
    short_leg = make_option(410, OptionRight.CALL, 2.0, 2.2)
    return TradeCandidate(
        trade_id="trd_fixture_bull_call",
        symbol="TEST",
        strategy=TradeStrategy.BULL_CALL_SPREAD,
        legs=(TradeLeg(long_leg, "BUY", 1), TradeLeg(short_leg, "SELL", 1)),
        rationale="fixture",
        max_profit=max_profit,
        max_loss=max_loss,
        breakeven=(405.0,),
        probability_estimate=None,
        score=TradeScoreBreakdown(20, 15, 10, 10, 8, 8, 4),
        size_tier=SizeTier.NORMAL_SIZE,
        created_at=datetime.now(timezone.utc),
    )
