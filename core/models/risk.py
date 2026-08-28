from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class RiskVerdict(str, Enum):
    APPROVE = "APPROVE"
    REDUCE_SIZE = "REDUCE_SIZE"
    REJECT = "REJECT"
    EMERGENCY_HALT = "EMERGENCY_HALT"


@dataclass(frozen=True, slots=True)
class RiskReason:
    rule: str
    passed: bool
    detail: str


@dataclass(frozen=True, slots=True)
class RiskDecision:
    verdict: RiskVerdict
    reasons: tuple[RiskReason, ...]
    approved_quantity: int | None = None  # set when verdict == REDUCE_SIZE

    @property
    def failed_rules(self) -> list[RiskReason]:
        return [r for r in self.reasons if not r.passed]

    def to_dict(self) -> dict:
        return {
            "verdict": self.verdict.value,
            "approved_quantity": self.approved_quantity,
            "reasons": [
                {"rule": r.rule, "passed": r.passed, "detail": r.detail} for r in self.reasons
            ],
        }
