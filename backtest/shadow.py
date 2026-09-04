"""
Shadow mode (Day-4 Phase 15).

Uses REAL CURRENT Alpaca data (via the same broker_factory/PortfolioState
machinery the live pipeline uses) to generate trade proposals, but NEVER
calls submit_order. Every proposal is stored with enough information to
score later against what actually happened.

This reuses core.orchestration.pipeline.run_pipeline's decision logic
directly rather than duplicating it — a shadow proposal is decided
exactly the way a real one would be, it's just never submitted.

NOT LIVE-VERIFIED: like the rest of the real-Alpaca-dependent code in
this project, this has been written against the current adapter and
compiles/imports cleanly, but has not been executed against a live
account by Claude (no network/credentials in this sandbox).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime

from core.config.settings import Settings
from core.models.risk import RiskVerdict
from core.models.trade import TradeCandidate


@dataclass(frozen=True, slots=True)
class ShadowProposal:
    label: str = "SHADOW / HYPOTHETICAL"
    timestamp: str = ""
    underlying: str = ""
    strategy: str = ""
    legs: tuple = ()
    score: float = 0.0
    risk_verdict: str = ""
    risk_reasons: tuple[str, ...] = ()
    proposed_entry_debit_or_credit: float = 0.0
    proposed_max_profit: float = 0.0
    proposed_max_loss: float = 0.0
    execution_status: str = "SHADOW_ONLY_NO_ORDER_SUBMITTED"
    later_observed_result: dict | None = None  # filled in by score_shadow_proposal(), never at creation time

    def to_dict(self) -> dict:
        d = asdict(self)
        return d


def build_shadow_proposal(candidate: TradeCandidate, risk_verdict: RiskVerdict, risk_reasons: tuple[str, ...]) -> ShadowProposal:
    entry = sum(
        (leg.contract.ask if leg.side == "BUY" else -leg.contract.bid) for leg in candidate.legs
    )
    return ShadowProposal(
        timestamp=datetime.now(UTC).isoformat(),
        underlying=candidate.symbol,
        strategy=candidate.strategy.value,
        legs=tuple(f"{leg.side} {leg.contract.right.value} {leg.contract.strike} exp {leg.contract.expiration}" for leg in candidate.legs),
        score=candidate.score.total,
        risk_verdict=risk_verdict.value,
        risk_reasons=risk_reasons,
        proposed_entry_debit_or_credit=round(entry, 4),
        proposed_max_profit=candidate.max_profit if candidate.max_profit != float("inf") else -1,
        proposed_max_loss=candidate.max_loss,
    )


def run_shadow_scan(settings: Settings, symbols: list[str] | None = None) -> list[ShadowProposal]:
    """
    Runs the REAL pipeline (via broker_factory — will use the real Alpaca
    adapter if EXECUTION_MODE is a PAPER_* mode with valid credentials, or
    the mock adapter for DRY_RUN) and converts every APPROVE/REDUCE_SIZE
    opportunity into a ShadowProposal. NEVER calls submit_order — this
    function doesn't even import anything that could.
    """
    from core.orchestration.pipeline import run_pipeline
    from integrations.broker_factory import get_broker_adapter

    broker = get_broker_adapter(settings)
    result = run_pipeline(settings, broker, symbols=symbols)

    proposals = []
    for entry in result.journal_entries:
        if entry.risk_decision in ("APPROVE", "REDUCE_SIZE"):
            proposals.append(
                ShadowProposal(
                    timestamp=datetime.now(UTC).isoformat(),
                    underlying=entry.symbol, strategy=entry.strategy.value, score=entry.score,
                    risk_verdict=entry.risk_decision, risk_reasons=tuple(entry.risk_reasons),
                    proposed_entry_debit_or_credit=entry.entry_debit_or_credit,
                    proposed_max_profit=entry.max_profit, proposed_max_loss=entry.max_loss,
                )
            )
    return proposals


def score_shadow_proposal(proposal: ShadowProposal, later_underlying_price: float) -> ShadowProposal:
    """Evaluates a stored proposal against a LATER observed price — always
    labeled SHADOW / HYPOTHETICAL, never conflated with a real fill."""
    from dataclasses import replace

    return replace(
        proposal,
        later_observed_result={
            "label": "SHADOW / HYPOTHETICAL",
            "later_underlying_price": later_underlying_price,
            "note": "hypothetical outcome only — no real position was ever opened",
        },
    )
