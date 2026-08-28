from __future__ import annotations

from core.models.risk import RiskVerdict
from risk.limits import PortfolioState, RiskPolicy, TradeRiskRequest
from risk.veto import RiskSentinel
from tests.fixtures.sample_data import make_bull_call_candidate


def _sentinel(settings) -> RiskSentinel:
    return RiskSentinel(settings, RiskPolicy(name="test"))


def test_clean_trade_is_approved(settings):
    portfolio = PortfolioState(equity=100_000, buying_power=200_000, daily_pnl=0, peak_equity=100_000)
    req = TradeRiskRequest(
        candidate=make_bull_call_candidate(max_loss=500), portfolio=portfolio,
        proposed_quantity=1, client_order_id="cid_approve",
    )
    decision = _sentinel(settings).evaluate(req)
    assert decision.verdict == RiskVerdict.APPROVE
    assert decision.approved_quantity == 1
    assert all(r.passed for r in decision.reasons)


def test_oversized_trade_risk_is_rejected(settings):
    """A trade whose max_loss alone blows through every size-adjustable limit
    (with proposed_quantity=1) cannot be sized down to zero and back to safety
    — it should be an outright REJECT, not REDUCE_SIZE."""
    portfolio = PortfolioState(equity=10_000, buying_power=20_000, daily_pnl=0, peak_equity=10_000)
    req = TradeRiskRequest(
        candidate=make_bull_call_candidate(max_loss=5_000), portfolio=portfolio,
        proposed_quantity=1, client_order_id="cid_reject_size",
    )
    decision = _sentinel(settings).evaluate(req)
    assert decision.verdict == RiskVerdict.REJECT
    assert "max_trade_risk" in [r.rule for r in decision.failed_rules]


def test_requesting_too_many_contracts_reduces_to_an_affordable_size(settings):
    portfolio = PortfolioState(equity=10_000, buying_power=20_000, daily_pnl=0, peak_equity=10_000)
    req = TradeRiskRequest(
        candidate=make_bull_call_candidate(max_loss=80), portfolio=portfolio,
        proposed_quantity=5, client_order_id="cid_reduce",
    )
    decision = _sentinel(settings).evaluate(req)
    assert decision.verdict == RiskVerdict.REDUCE_SIZE
    assert 0 < decision.approved_quantity < 5


def test_stale_market_data_is_rejected_even_with_ample_capital(settings):
    portfolio = PortfolioState(
        equity=100_000, buying_power=200_000, daily_pnl=0, peak_equity=100_000,
        market_data_is_stale=True,
    )
    req = TradeRiskRequest(
        candidate=make_bull_call_candidate(max_loss=50), portfolio=portfolio,
        proposed_quantity=1, client_order_id="cid_stale",
    )
    decision = _sentinel(settings).evaluate(req)
    assert decision.verdict == RiskVerdict.REJECT
    assert "stale_data" in [r.rule for r in decision.failed_rules]


def test_duplicate_client_order_id_is_rejected(settings):
    portfolio = PortfolioState(
        equity=100_000, buying_power=200_000, daily_pnl=0, peak_equity=100_000,
        recent_client_order_ids=("cid_dupe",),
    )
    req = TradeRiskRequest(
        candidate=make_bull_call_candidate(max_loss=50), portfolio=portfolio,
        proposed_quantity=1, client_order_id="cid_dupe",
    )
    decision = _sentinel(settings).evaluate(req)
    assert decision.verdict == RiskVerdict.REJECT
    assert "duplicate_order" in [r.rule for r in decision.failed_rules]


def test_drawdown_breach_triggers_emergency_halt_regardless_of_trade_quality(settings):
    """This is the key differentiator test: even a small, otherwise-clean
    trade must be halted once account-wide drawdown breaches the limit."""
    portfolio = PortfolioState(equity=8_500, buying_power=20_000, daily_pnl=0, peak_equity=10_000)
    req = TradeRiskRequest(
        candidate=make_bull_call_candidate(max_loss=50), portfolio=portfolio,
        proposed_quantity=1, client_order_id="cid_halt",
    )
    decision = _sentinel(settings).evaluate(req)
    assert decision.verdict == RiskVerdict.EMERGENCY_HALT


def test_consecutive_rejections_trigger_emergency_halt(settings):
    portfolio = PortfolioState(
        equity=100_000, buying_power=200_000, daily_pnl=0, peak_equity=100_000,
        consecutive_risk_rejections=5,
    )
    req = TradeRiskRequest(
        candidate=make_bull_call_candidate(max_loss=50), portfolio=portfolio,
        proposed_quantity=1, client_order_id="cid_halt2",
    )
    decision = _sentinel(settings).evaluate(req)
    assert decision.verdict == RiskVerdict.EMERGENCY_HALT


def test_high_score_trade_can_still_be_rejected_on_concentration():
    """Direct regression test for the spec's headline claim: 'Trade Score: 94,
    AI Decision: BUY, Risk Sentinel: REJECT'. Score never overrides risk."""
    from core.config.settings import Settings
    settings = Settings()
    portfolio = PortfolioState(equity=10_000, buying_power=20_000, daily_pnl=0, peak_equity=10_000)
    req = TradeRiskRequest(
        candidate=make_bull_call_candidate(max_loss=2_500), portfolio=portfolio,
        proposed_quantity=1, client_order_id="cid_conc",
    )
    decision = _sentinel(settings).evaluate(req)
    assert decision.verdict == RiskVerdict.REJECT
