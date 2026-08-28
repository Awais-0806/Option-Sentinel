"""
RiskSentinel — the component with final authority over every trade.

Even a 95/100 scored trade can be rejected here. That veto, and the
reasons behind it, are recorded to the audit trail and surfaced in the
dashboard timeline. This is the system's core safety differentiator.
"""
from __future__ import annotations

import logging

from core.config.settings import Settings
from core.models.risk import RiskDecision, RiskReason, RiskVerdict
from risk.circuit_breaker import CircuitBreaker
from risk.limits import RiskPolicy, TradeRiskRequest
from risk.sizing import max_affordable_quantity

logger = logging.getLogger("optionsentinel.risk")

# Rules whose *only* failure mode is "too much size" — these are the ones
# eligible for REDUCE_SIZE instead of an outright REJECT.
SIZE_ADJUSTABLE_RULES = {
    "buying_power",
    "max_trade_risk",
    "max_portfolio_risk",
    "position_concentration",
}


class RiskSentinel:
    def __init__(self, settings: Settings, policy: RiskPolicy, circuit_breaker: CircuitBreaker | None = None):
        self.settings = settings
        self.policy = policy
        self.circuit_breaker = circuit_breaker or CircuitBreaker(settings)

    def evaluate(self, req: TradeRiskRequest) -> RiskDecision:
        # Circuit breaker runs first — if the account is already in a halt
        # state, nothing else matters.
        halt_reason = self.circuit_breaker.check(req.portfolio)
        if halt_reason is not None:
            reasons = (RiskReason(rule="circuit_breaker", passed=False, detail=halt_reason),)
            logger.critical("EMERGENCY_HALT: %s", halt_reason)
            return RiskDecision(verdict=RiskVerdict.EMERGENCY_HALT, reasons=reasons)

        reasons: list[RiskReason] = [rule(req, self.settings) for rule in self.policy.rules]
        failed = [r for r in reasons if not r.passed]

        if not failed:
            logger.info("RISK_APPROVED trade_id=%s", req.candidate.trade_id)
            return RiskDecision(
                verdict=RiskVerdict.APPROVE,
                reasons=tuple(reasons),
                approved_quantity=req.proposed_quantity,
            )

        hard_failures = [r for r in failed if r.rule not in SIZE_ADJUSTABLE_RULES]
        if hard_failures:
            logger.warning(
                "RISK_REJECTED trade_id=%s reasons=%s",
                req.candidate.trade_id,
                [r.rule for r in hard_failures],
            )
            return RiskDecision(verdict=RiskVerdict.REJECT, reasons=tuple(reasons))

        # Only size-adjustable rules failed — see if a smaller quantity clears them all.
        reduced_qty = max_affordable_quantity(req, self.settings)
        if reduced_qty and reduced_qty > 0:
            logger.info(
                "RISK_REDUCE_SIZE trade_id=%s original_qty=%d approved_qty=%d",
                req.candidate.trade_id, req.proposed_quantity, reduced_qty,
            )
            return RiskDecision(
                verdict=RiskVerdict.REDUCE_SIZE,
                reasons=tuple(reasons),
                approved_quantity=reduced_qty,
            )

        logger.warning("RISK_REJECTED trade_id=%s reasons=size_unrecoverable", req.candidate.trade_id)
        return RiskDecision(verdict=RiskVerdict.REJECT, reasons=tuple(reasons))
