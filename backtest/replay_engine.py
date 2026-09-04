"""
Leakage-safe replay engine (Phase F).

The core guarantee: `decide_at(dataset, as_of, portfolio)` is a PURE
function of `dataset.as_of_or_earlier(as_of)` — it is structurally
impossible for it to read `dataset.days` for any date after `as_of`,
because the very first thing this function does is discard everything
after `as_of` and only ever operates on the truncated copy from that
point forward. Every other function in this module receives that
truncated dataset, never the original.

This is proven, not just asserted — see
tests/backtest/test_replay_engine_leakage.py, which mutates future days
and asserts the decision at T is byte-identical.

Reuses the EXISTING regime classifier / strategy selector / risk sentinel
components unchanged — the backtest is not a separate, parallel decision
engine that could drift from the live pipeline (core/orchestration/pipeline.py).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime

from agents.options_analyst.validator import OptionContractValidator
from agents.regime.classifier import RegimeClassifier
from agents.strategy.selector import StrategySelector
from backtest.data_schema import HistoricalDataset
from core.config.settings import Settings
from core.models.market import MarketRegime, PriceBar
from core.models.options import OptionChainSlice
from core.models.risk import RiskDecision
from core.models.trade import TradeCandidate
from risk.limits import PortfolioState, RiskPolicy, TradeRiskRequest
from risk.veto import RiskSentinel

REGIME_LOOKBACK_DAYS = 90  # must match RegimeClassifier.TREND_WINDOW_SLOW + margin


@dataclass(frozen=True, slots=True)
class ReplayDecision:
    as_of: date
    regime: MarketRegime
    candidate: TradeCandidate | None
    risk_decision: RiskDecision | None
    rejected_contract_count: int


def _bars_up_to(dataset: HistoricalDataset, as_of: date) -> list[PriceBar]:
    """Derived strictly from `dataset` (already truncated by the caller).
    Each HistoricalDay carries only a single daily close (Phase A found no
    real intraday OHLC in any available source), so open=high=low=close is
    a disclosed simplification — see docs/ARCHITECTURE.md backtest notes."""
    return [
        PriceBar(
            timestamp=datetime.combine(day.as_of_date, datetime.min.time(), tzinfo=UTC),
            open=day.underlying_close, high=day.underlying_close,
            low=day.underlying_close, close=day.underlying_close, volume=0,
        )
        for day in dataset.days
        if day.as_of_date <= as_of
    ]


def decide_at(
    dataset: HistoricalDataset,
    as_of: date,
    portfolio: PortfolioState,
    settings: Settings,
    *,
    strategy_selector: StrategySelector | None = None,
    risk_sentinel: RiskSentinel | None = None,
    skip_contract_validation: bool = False,
    forced_strategy=None,
) -> ReplayDecision:
    """
    THE leakage boundary. `visible` below is the ONLY dataset reference
    used anywhere in this function or anything it calls — the original
    `dataset` parameter (which may contain future days) is never touched
    again after this line.

    `skip_contract_validation` and `forced_strategy` exist ONLY to build
    baseline comparisons (Phase H) that are structurally forced to differ
    from the full pipeline in one specific, named way — they are never
    used for the actual OptionSentinel decision path.
    """
    visible = dataset.as_of_or_earlier(as_of)

    day = next((d for d in visible.days if d.as_of_date == as_of), None)
    if day is None:
        # as_of isn't a day present in the dataset (e.g. weekend/holiday) — nothing to decide.
        from core.models.market import RegimeLabel
        empty_regime = MarketRegime(symbol=dataset.underlying, regime=RegimeLabel.UNCERTAIN, confidence=0.0, features={})
        return ReplayDecision(as_of=as_of, regime=empty_regime, candidate=None, risk_decision=None, rejected_contract_count=0)

    bars = _bars_up_to(visible, as_of)
    regime = RegimeClassifier().classify(dataset.underlying, bars)

    raw_chain = OptionChainSlice(underlying=dataset.underlying, fetched_at=as_of.isoformat(), contracts=day.contracts)
    if skip_contract_validation:
        filtered_chain, rejections = raw_chain, []
    else:
        validator = OptionContractValidator(settings, today=as_of)
        filtered_chain, rejections = validator.filter_chain(raw_chain)

    from strategies.base import StrategyContext
    ctx = StrategyContext(
        symbol=dataset.underlying, underlying_price=day.underlying_close, regime=regime,
        chain=filtered_chain, settings=settings,
        now=datetime.combine(as_of, datetime.min.time(), tzinfo=UTC),
    )

    if forced_strategy is not None:
        candidate = forced_strategy.build_trade(ctx)
        if candidate is not None:
            ok, _problems = forced_strategy.validate(ctx, candidate)
            if not ok:
                candidate = None
        if candidate is not None:
            from dataclasses import replace as _replace

            from agents.strategy.scoring import size_tier_for_score
            candidate = _replace(candidate, size_tier=size_tier_for_score(candidate.score.total, settings))
    else:
        selector = strategy_selector or StrategySelector(settings)
        candidate = selector.select(ctx)

    if candidate is None:
        return ReplayDecision(as_of=as_of, regime=regime, candidate=None, risk_decision=None, rejected_contract_count=len(rejections))

    from core.models.trade import SizeTier
    if candidate.size_tier == SizeTier.NO_TRADE:
        return ReplayDecision(as_of=as_of, regime=regime, candidate=candidate, risk_decision=None, rejected_contract_count=len(rejections))

    sentinel = risk_sentinel or RiskSentinel(settings, RiskPolicy(name="backtest"))
    risk_req = TradeRiskRequest(
        candidate=candidate, portfolio=portfolio, proposed_quantity=1,
        client_order_id=f"backtest_{dataset.underlying}_{as_of.isoformat()}_{candidate.trade_id}",
        now=datetime.combine(as_of, datetime.min.time(), tzinfo=UTC),
    )
    decision = sentinel.evaluate(risk_req)

    return ReplayDecision(as_of=as_of, regime=regime, candidate=candidate, risk_decision=decision, rejected_contract_count=len(rejections))
