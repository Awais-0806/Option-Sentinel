from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from core.models.market import MarketRegime, RegimeLabel
from core.models.options import OptionChainSlice, OptionContract, OptionRight
from strategies.base import StrategyContext
from strategies.bear_put_spread import BearPutSpreadStrategy
from strategies.bull_call_spread import BullCallSpreadStrategy
from strategies.iron_condor import IronCondorStrategy
from strategies.long_volatility import LongVolatilityStrategy


def _synthetic_chain(spot: float, dte_list=(30,)) -> OptionChainSlice:
    today = date.today()
    contracts = []
    for dte in dte_list:
        exp = today + timedelta(days=dte)
        for strike in [round(spot * m, 1) for m in (0.85, 0.90, 0.93, 0.95, 1.00, 1.05, 1.07, 1.10, 1.15)]:
            for right in (OptionRight.CALL, OptionRight.PUT):
                intrinsic = max(spot - strike, 0) if right == OptionRight.CALL else max(strike - spot, 0)
                distance = abs(strike - spot)
                time_value = max(spot * 0.035 - distance * 0.22, 0.05)
                fair = round(intrinsic + time_value, 2)
                contracts.append(
                    OptionContract(
                        symbol=f"T{strike}{right.value}", underlying="TEST", expiration=exp,
                        strike=strike, right=right, bid=round(fair * 0.97, 2), ask=round(fair * 1.03, 2),
                        last=round(fair, 2), volume=200, open_interest=1000, implied_volatility=0.25,
                    )
                )
    return OptionChainSlice(underlying="TEST", fetched_at="now", contracts=tuple(contracts))


def _ctx(regime_label: RegimeLabel, confidence: float, spot: float = 100.0, features: dict | None = None) -> StrategyContext:
    from core.config.settings import Settings
    regime = MarketRegime(symbol="TEST", regime=regime_label, confidence=confidence, features=features or {})
    return StrategyContext(
        symbol="TEST", underlying_price=spot, regime=regime,
        chain=_synthetic_chain(spot), settings=Settings(),
    )


def test_bull_call_spread_eligible_only_on_bullish_regime():
    strat = BullCallSpreadStrategy()
    assert strat.evaluate(_ctx(RegimeLabel.BULLISH, 0.8)) is True
    assert strat.evaluate(_ctx(RegimeLabel.BEARISH, 0.8)) is False
    assert strat.evaluate(_ctx(RegimeLabel.BULLISH, 0.3)) is False  # below confidence floor


def test_bull_call_spread_builds_a_valid_defined_risk_trade():
    ctx = _ctx(RegimeLabel.BULLISH, 0.8)
    strat = BullCallSpreadStrategy()
    candidate = strat.build_trade(ctx)
    assert candidate is not None
    ok, problems = strat.validate(ctx, candidate)
    assert ok, problems
    assert candidate.max_loss > 0
    assert candidate.max_profit > 0
    long_leg, short_leg = candidate.legs
    assert long_leg.contract.strike < short_leg.contract.strike
    assert long_leg.side == "BUY" and short_leg.side == "SELL"


def test_bear_put_spread_eligible_only_on_bearish_regime():
    strat = BearPutSpreadStrategy()
    assert strat.evaluate(_ctx(RegimeLabel.BEARISH, 0.8)) is True
    assert strat.evaluate(_ctx(RegimeLabel.BULLISH, 0.8)) is False


def test_bear_put_spread_builds_a_valid_defined_risk_trade():
    ctx = _ctx(RegimeLabel.BEARISH, 0.8)
    strat = BearPutSpreadStrategy()
    candidate = strat.build_trade(ctx)
    assert candidate is not None
    ok, problems = strat.validate(ctx, candidate)
    assert ok, problems
    long_leg, short_leg = candidate.legs
    assert long_leg.contract.strike > short_leg.contract.strike


def test_iron_condor_requires_range_regime_and_sufficient_iv():
    strat = IronCondorStrategy()
    eligible = _ctx(RegimeLabel.RANGE, 0.8, features={"realized_vol_annualized": 0.25})
    not_enough_iv = _ctx(RegimeLabel.RANGE, 0.8, features={"realized_vol_annualized": 0.05})
    wrong_regime = _ctx(RegimeLabel.BULLISH, 0.8, features={"realized_vol_annualized": 0.25})
    assert strat.evaluate(eligible) is True
    assert strat.evaluate(not_enough_iv) is False
    assert strat.evaluate(wrong_regime) is False


def test_iron_condor_builds_four_legs_in_ascending_strike_order():
    ctx = _ctx(RegimeLabel.RANGE, 0.8, features={"realized_vol_annualized": 0.25})
    strat = IronCondorStrategy()
    candidate = strat.build_trade(ctx)
    assert candidate is not None
    ok, problems = strat.validate(ctx, candidate)
    assert ok, problems
    assert len(candidate.legs) == 4
    strikes = [leg.contract.strike for leg in candidate.legs]
    assert strikes == sorted(strikes)


def test_long_volatility_requires_high_confidence_high_vol_regime():
    strat = LongVolatilityStrategy()
    strong_signal = _ctx(RegimeLabel.HIGH_VOLATILITY, 0.8)
    weak_signal = _ctx(RegimeLabel.HIGH_VOLATILITY, 0.5)  # below the strategy's own stricter floor
    assert strat.evaluate(strong_signal) is True
    assert strat.evaluate(weak_signal) is False


def test_long_volatility_is_not_eligible_for_every_regime():
    """Guards the spec requirement: 'Do not implement a reckless trade
    everything system.' This strategy must stay the most selective one."""
    strat = LongVolatilityStrategy()
    for label in (RegimeLabel.BULLISH, RegimeLabel.BEARISH, RegimeLabel.RANGE, RegimeLabel.LOW_VOLATILITY):
        assert strat.evaluate(_ctx(label, 0.9)) is False
