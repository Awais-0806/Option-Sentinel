"""
End-to-end pipeline (Milestone 10):

  Market Scan -> Regime -> Options Scan -> Strategy -> Score -> Risk
  -> (Simulated) Execution -> Journal

The default EXECUTION_MODE is DRY_RUN, enforced by Settings, not by
convention here — this module runs identically across DRY_RUN,
PAPER_SIMULATION, PAPER_MANUAL_APPROVAL, and PAPER_AUTONOMOUS.
Settings.execution_mode (via broker_factory for adapter selection, and
_maybe_submit() below for order-submission gating) decides which one
without any code change here.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from core.config.settings import ExecutionMode, Settings
from core.events.logging_config import (
    EVENT_MARKET_SCAN_COMPLETED,
    EVENT_MARKET_SCAN_STARTED,
    EVENT_OPPORTUNITY_FOUND,
    EVENT_ORDER_SUBMITTED,
    EVENT_RISK_APPROVED,
    EVENT_RISK_REJECTED,
    EVENT_STRATEGY_SELECTED,
)
from core.interfaces.broker import BrokerAdapter
from core.models.risk import RiskVerdict
from core.models.trade import SizeTier, TradeJournalEntry
from agents.regime.classifier import RegimeClassifier
from agents.strategy.selector import StrategySelector
from risk.limits import PortfolioState, RiskPolicy, TradeRiskRequest
from risk.veto import RiskSentinel
from strategies.base import StrategyContext

logger = logging.getLogger("optionsentinel.pipeline")


class PipelineResult:
    def __init__(self):
        self.journal_entries: list[TradeJournalEntry] = []

    def add(self, entry: TradeJournalEntry) -> None:
        self.journal_entries.append(entry)

    def summary(self) -> dict:
        by_verdict: dict[str, int] = {}
        for e in self.journal_entries:
            by_verdict[e.risk_decision] = by_verdict.get(e.risk_decision, 0) + 1
        return {
            "symbols_scanned": len(self.journal_entries),
            "by_risk_decision": by_verdict,
            "opportunities": [e.to_dict() for e in self.journal_entries],
        }


def run_pipeline(
    settings: Settings,
    broker: BrokerAdapter,
    symbols: list[str] | None = None,
) -> PipelineResult:
    symbols = symbols or settings.watchlist_symbols
    result = PipelineResult()

    regime_classifier = RegimeClassifier()
    strategy_selector = StrategySelector(settings)
    risk_sentinel = RiskSentinel(settings, RiskPolicy(name="default"))

    account = broker.get_account()
    portfolio = PortfolioState(
        equity=account.equity,
        buying_power=account.buying_power,
        daily_pnl=account.daily_pnl,
        peak_equity=account.peak_equity,
        open_positions=tuple(),
        recent_client_order_ids=tuple(),
    )

    logger.info(EVENT_MARKET_SCAN_STARTED, extra={"event": EVENT_MARKET_SCAN_STARTED, "context": {"symbols": symbols}})

    for symbol in symbols:
        bars = broker.get_price_bars(symbol, lookback_days=90)
        regime = regime_classifier.classify(symbol, bars)
        logger.info(
            "regime classified", extra={"event": "REGIME_CLASSIFIED", "context": regime.to_dict()}
        )

        chain = broker.get_option_chain(symbol, min_dte=14, max_dte=45)
        ctx = StrategyContext(
            symbol=symbol,
            underlying_price=bars[-1].close if bars else 0.0,
            regime=regime,
            chain=chain,
            settings=settings,
            now=datetime.now(timezone.utc),
        )

        candidate = strategy_selector.select(ctx)
        if candidate is None:
            continue

        logger.info(
            EVENT_OPPORTUNITY_FOUND,
            extra={"event": EVENT_OPPORTUNITY_FOUND, "context": {"symbol": symbol, "trade_id": candidate.trade_id}},
        )
        logger.info(
            EVENT_STRATEGY_SELECTED,
            extra={"event": EVENT_STRATEGY_SELECTED, "context": {"strategy": candidate.strategy.value}},
        )

        # No-trade tier is a legitimate outcome — journal it, don't risk-check it.
        if candidate.size_tier == SizeTier.NO_TRADE:
            result.add(_journal_entry(candidate, regime, risk_decision="NO_TRADE",
                                       risk_reasons=("score below SCORE_NO_TRADE_MAX",)))
            continue

        client_order_id = f"cid_{uuid.uuid4().hex[:16]}"
        risk_req = TradeRiskRequest(
            candidate=candidate,
            portfolio=portfolio,
            proposed_quantity=1,
            client_order_id=client_order_id,
        )
        decision = risk_sentinel.evaluate(risk_req)

        if decision.verdict == RiskVerdict.APPROVE or decision.verdict == RiskVerdict.REDUCE_SIZE:
            logger.info(EVENT_RISK_APPROVED, extra={"event": EVENT_RISK_APPROVED,
                        "context": {"trade_id": candidate.trade_id, "verdict": decision.verdict.value}})

            order_status, order_id = _maybe_submit(
                settings, broker, candidate, decision, client_order_id
            )

            result.add(_journal_entry(
                candidate, regime,
                risk_decision=decision.verdict.value,
                risk_reasons=tuple(r.detail for r in decision.failed_rules) or ("all checks passed",),
                order_id=order_id,
                execution_status=order_status,
            ))
        else:
            logger.warning(EVENT_RISK_REJECTED, extra={"event": EVENT_RISK_REJECTED,
                            "context": {"trade_id": candidate.trade_id, "verdict": decision.verdict.value}})
            result.add(_journal_entry(
                candidate, regime,
                risk_decision=decision.verdict.value,
                risk_reasons=tuple(r.detail for r in decision.failed_rules),
            ))

    logger.info(EVENT_MARKET_SCAN_COMPLETED, extra={"event": EVENT_MARKET_SCAN_COMPLETED,
                "context": {"opportunities_found": len(result.journal_entries)}})
    return result


def _maybe_submit(settings, broker, candidate, decision, client_order_id):
    """
    Order submission is gated strictly by execution_mode, mirroring the
    same mode ladder broker_factory.get_broker_adapter() uses for adapter
    selection:

        DRY_RUN / PAPER_SIMULATION   -> never submit; broker is the mock
                                         adapter anyway (belt-and-braces).
        PAPER_MANUAL_APPROVAL        -> build + risk-check, but STOP here
                                         and wait for explicit operator
                                         approval (see Phase E — approval
                                         UI/CLI not yet implemented; the
                                         pipeline correctly refuses to
                                         auto-submit in this mode today).
        PAPER_AUTONOMOUS             -> approved trades submit automatically.

    Returns (order_status, order_id).
    """
    if settings.execution_mode == ExecutionMode.PAPER_MANUAL_APPROVAL:
        logger.info(
            "AWAITING_MANUAL_APPROVAL trade_id=%s — built and risk-checked, "
            "not submitted (manual approval flow not yet implemented)",
            candidate.trade_id,
        )
        return "AWAITING_MANUAL_APPROVAL", None

    if settings.execution_mode != ExecutionMode.PAPER_AUTONOMOUS:
        return "SKIPPED_DRY_RUN", None

    order = broker.submit_order(
        legs=list(candidate.legs),
        quantity=decision.approved_quantity or 1,
        client_order_id=client_order_id,
        limit_price=None,
    )
    logger.info(
        EVENT_ORDER_SUBMITTED,
        extra={"event": EVENT_ORDER_SUBMITTED, "context": {"order_id": order.order_id, "status": order.status}},
    )
    return order.status, order.order_id


def _journal_entry(
    candidate, regime, *, risk_decision: str, risk_reasons: tuple[str, ...],
    order_id: str | None = None, execution_status: str = "PENDING",
) -> TradeJournalEntry:
    # Net debit (positive) or net credit (negative) across all legs, per share.
    # BUY legs cost money (add), SELL legs bring money in (subtract).
    entry_price = round(
        sum(
            leg.contract.mid * (1 if leg.side == "BUY" else -1)
            for leg in candidate.legs
        ),
        4,
    )
    return TradeJournalEntry(
        trade_id=candidate.trade_id,
        timestamp=candidate.created_at,
        symbol=candidate.symbol,
        strategy=candidate.strategy,
        regime=regime.regime.value,
        score=candidate.score.total,
        entry_debit_or_credit=entry_price,
        max_profit=candidate.max_profit if candidate.max_profit != float("inf") else -1,
        max_loss=candidate.max_loss,
        probability_estimate=candidate.probability_estimate,
        risk_decision=risk_decision,
        risk_reasons=risk_reasons,
        order_id=order_id,
        execution_status=execution_status,
    )
