"""
Phase N: "Add tests against hand-calculated examples."

Every expected value below was computed by hand in the docstring/comment
BEFORE being pasted into the assertion — not derived by running the code
and copying its output.
"""
from __future__ import annotations

from datetime import UTC, date, datetime

from backtest.pnl import COST_BASE, CostAssumptions, entry_to_expiration_pnl
from core.models.options import OptionContract, OptionRight
from core.models.trade import TradeCandidate, TradeLeg, TradeScoreBreakdown, TradeStrategy


def _bull_call_candidate() -> TradeCandidate:
    long_call = OptionContract(
        symbol="LONG", underlying="TEST", expiration=date(2026, 3, 20), strike=100,
        right=OptionRight.CALL, bid=5.00, ask=5.20, last=5.10, volume=100, open_interest=500,
    )
    short_call = OptionContract(
        symbol="SHORT", underlying="TEST", expiration=date(2026, 3, 20), strike=110,
        right=OptionRight.CALL, bid=2.00, ask=2.20, last=2.10, volume=100, open_interest=500,
    )
    return TradeCandidate(
        trade_id="trd_handcalc", symbol="TEST", strategy=TradeStrategy.BULL_CALL_SPREAD,
        legs=(TradeLeg(long_call, "BUY", 1), TradeLeg(short_call, "SELL", 1)),
        rationale="hand-calc fixture", max_profit=680.0, max_loss=320.0, breakeven=(103.2,),
        probability_estimate=None, score=TradeScoreBreakdown(20, 15, 10, 10, 8, 8, 4),
        size_tier=None, created_at=datetime.now(UTC),
    )


def test_bull_call_spread_max_profit_scenario_hand_calculated():
    """
    HAND CALCULATION:
      Entry: BUY call@100 at ask=5.20, SELL call@110 at bid=2.00
      Net debit = 5.20 - 2.00 = 3.20/share = $320/spread
      Expiration underlying = 115 (both legs deep ITM, spread at max width)
      Long call intrinsic = max(115-100, 0) = 15
      Short call intrinsic = max(115-110, 0) = 5
      Net exit value = 15 - 5 = 10/share = $1000/spread
      Gross P&L = (10 - 3.20) * 100 = $680.00  <- matches candidate.max_profit exactly
      Fees (COST_BASE $0.65/contract, 2 legs, open+close) = 0.65 * 2 * 1 * 2 = $2.60
      Net P&L = 680.00 - 2.60 = $677.40
    """
    candidate = _bull_call_candidate()
    execution = entry_to_expiration_pnl(candidate, date(2026, 2, 18), underlying_price_at_expiration=115.0)

    assert execution.entry_price == 3.20
    assert execution.exit_price == 10.0
    assert execution.gross_pnl == 680.0
    assert execution.fees == 2.60
    assert execution.net_pnl == 677.40


def test_bull_call_spread_max_loss_scenario_hand_calculated():
    """
    HAND CALCULATION:
      Same entry: net debit = 3.20/share = $320/spread
      Expiration underlying = 95 (both legs OTM, worthless)
      Both intrinsic values = 0
      Net exit value = 0
      Gross P&L = (0 - 3.20) * 100 = -$320.00  <- matches candidate.max_loss exactly (sign flipped)
      Fees = $2.60
      Net P&L = -320.00 - 2.60 = -$322.60
    """
    candidate = _bull_call_candidate()
    execution = entry_to_expiration_pnl(candidate, date(2026, 2, 18), underlying_price_at_expiration=95.0)

    assert execution.gross_pnl == -320.0
    assert execution.gross_pnl == -candidate.max_loss  # gross loss cannot exceed the strategy's own defined max loss
    assert execution.net_pnl == -322.60


def test_bull_call_spread_breakeven_scenario_hand_calculated():
    """
    HAND CALCULATION:
      Breakeven = long strike + net debit = 100 + 3.20 = 103.20
      At underlying = 103.20:
        Long call intrinsic = 3.20, short call intrinsic = 0
        Net exit value = 3.20
      Gross P&L = (3.20 - 3.20) * 100 = $0.00 exactly
      Net P&L = 0.00 - 2.60 (fees) = -$2.60 (costs make true breakeven slightly worse than the textbook number)
    """
    candidate = _bull_call_candidate()
    execution = entry_to_expiration_pnl(candidate, date(2026, 2, 18), underlying_price_at_expiration=103.20)

    assert execution.gross_pnl == 0.0
    assert execution.net_pnl == -2.60


def test_zero_cost_assumption_matches_gross_pnl_exactly():
    zero_cost = CostAssumptions(commission_per_contract=0.0, slippage_pct_of_mid=0.0, label="LOW_COST")
    candidate = _bull_call_candidate()
    execution = entry_to_expiration_pnl(
        candidate, date(2026, 2, 18), underlying_price_at_expiration=115.0, cost=zero_cost
    )
    assert execution.net_pnl == execution.gross_pnl == 680.0


def test_higher_cost_assumption_produces_strictly_worse_net_pnl():
    from backtest.pnl import COST_HIGH

    candidate = _bull_call_candidate()
    base = entry_to_expiration_pnl(candidate, date(2026, 2, 18), underlying_price_at_expiration=115.0, cost=COST_BASE)
    high = entry_to_expiration_pnl(candidate, date(2026, 2, 18), underlying_price_at_expiration=115.0, cost=COST_HIGH)
    assert high.net_pnl < base.net_pnl


def test_quantity_scales_pnl_linearly():
    candidate = _bull_call_candidate()
    qty1 = entry_to_expiration_pnl(candidate, date(2026, 2, 18), underlying_price_at_expiration=115.0, quantity=1)
    qty3 = entry_to_expiration_pnl(candidate, date(2026, 2, 18), underlying_price_at_expiration=115.0, quantity=3)
    # gross scales exactly; fees scale per-contract, so net scales close to but not exactly 3x
    assert qty3.gross_pnl == qty1.gross_pnl * 3
    assert qty3.fees == round(qty1.fees * 3, 2)  # both sides rounded — avoids a float-precision false negative
