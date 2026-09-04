from __future__ import annotations

from datetime import date

from core.models.market import MarketRegime, RegimeLabel
from core.models.options import OptionChainSlice, OptionContract, OptionRight
from core.models.risk import RiskVerdict
from risk.limits import PortfolioState, RiskPolicy, TradeRiskRequest
from risk.veto import RiskSentinel
from strategies.base import StrategyContext
from strategies.bull_call_spread import BullCallSpreadStrategy
from tests.fixtures.sample_data import make_bull_call_candidate


def test_empty_option_chain_yields_no_trade_not_a_crash(settings):
    regime = MarketRegime(symbol="TEST", regime=RegimeLabel.BULLISH, confidence=0.9, features={})
    empty_chain = OptionChainSlice(underlying="TEST", fetched_at="now", contracts=())
    ctx = StrategyContext(symbol="TEST", underlying_price=100.0, regime=regime, chain=empty_chain, settings=settings)
    candidate = BullCallSpreadStrategy().build_trade(ctx)
    assert candidate is None  # must degrade gracefully, never raise


def test_zero_bid_ask_contract_is_flagged_unusable():
    bad = OptionContract(
        symbol="BAD", underlying="TEST", expiration=date(2026, 12, 1), strike=100,
        right=OptionRight.CALL, bid=0.0, ask=0.0, last=None, volume=0, open_interest=0,
    )
    assert bad.is_tradeable is False
    assert bad.mid == 0.0
    assert bad.spread_pct == 1.0  # worst-case, not a crash from div-by-zero


def test_missing_greeks_do_not_break_contract_construction():
    contract = OptionContract(
        symbol="NOGREEKS", underlying="TEST", expiration=date(2026, 12, 1), strike=100,
        right=OptionRight.PUT, bid=1.0, ask=1.2, last=1.1, volume=50, open_interest=200,
        implied_volatility=None, delta=None, gamma=None, theta=None, vega=None,
    )
    assert contract.is_tradeable is True
    assert contract.mid == 1.1


def test_insufficient_buying_power_is_rejected(settings):
    portfolio = PortfolioState(equity=100_000, buying_power=10.0, daily_pnl=0, peak_equity=100_000)
    req = TradeRiskRequest(
        candidate=make_bull_call_candidate(max_loss=500), portfolio=portfolio,
        proposed_quantity=1, client_order_id="cid_bp",
    )
    decision = RiskSentinel(settings, RiskPolicy(name="test")).evaluate(req)
    assert decision.verdict in (RiskVerdict.REJECT, RiskVerdict.REDUCE_SIZE)
    assert "buying_power" in [r.rule for r in decision.failed_rules]


def test_expired_contract_fails_contract_sanity(settings):
    expired = OptionContract(
        symbol="EXP", underlying="TEST", expiration=date(2020, 1, 1), strike=100,
        right=OptionRight.CALL, bid=1.0, ask=1.1, last=1.05, volume=10, open_interest=50,
    )
    from dataclasses import replace

    from core.models.trade import TradeLeg

    candidate = make_bull_call_candidate()
    candidate = replace(candidate, legs=(TradeLeg(expired, "BUY", 1), candidate.legs[1]))

    portfolio = PortfolioState(equity=100_000, buying_power=200_000, daily_pnl=0, peak_equity=100_000)
    req = TradeRiskRequest(candidate=candidate, portfolio=portfolio, proposed_quantity=1, client_order_id="cid_exp")
    decision = RiskSentinel(settings, RiskPolicy(name="test")).evaluate(req)
    assert decision.verdict == RiskVerdict.REJECT
    assert "contract_sanity" in [r.rule for r in decision.failed_rules]
