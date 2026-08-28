"""
Options Analyst — contract validation (Phase D).

Spec requirement: "Do not silently continue with invalid data. Every
rejection should have a reason." This module is the single gate every
contract passes through before a strategy is allowed to use it —
independent of (and in addition to) the Risk Sentinel's own
`contract_sanity` / `liquidity_spread` checks in risk/limits.py, which
re-check the *specific legs of a proposed trade*. This validator instead
filters the *raw chain* upstream, so strategies never even see garbage
contracts when selecting strikes.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone

from core.config.settings import Settings
from core.models.options import OptionChainSlice, OptionContract


@dataclass(frozen=True, slots=True)
class ContractRejection:
    contract_symbol: str
    reasons: tuple[str, ...]


class OptionContractValidator:
    """Stateless except for `settings` (thresholds) and an injectable
    `now`/quote-age reference, so it's deterministic and easy to unit test."""

    def __init__(self, settings: Settings, *, today: date | None = None):
        self.settings = settings
        self.today = today or datetime.now(timezone.utc).date()

    def validate(self, contract: OptionContract, *, quote_age_seconds: float | None = None) -> tuple[bool, list[str]]:
        reasons: list[str] = []

        # ── Malformed / missing required fields ──────────────────────
        if contract.strike is None or contract.strike <= 0:
            reasons.append(f"impossible strike: {contract.strike!r}")
        if contract.bid is None or contract.ask is None:
            reasons.append("missing bid/ask")
            return False, reasons  # nothing else below is safe to evaluate

        # ── Invalid bid/ask ───────────────────────────────────────────
        if contract.bid < 0 or contract.ask < 0:
            reasons.append(f"negative bid/ask: bid={contract.bid} ask={contract.ask}")
        elif contract.ask < contract.bid:
            reasons.append(f"crossed quote: ask ({contract.ask}) < bid ({contract.bid})")
        elif contract.bid == 0 and contract.ask == 0:
            reasons.append("zero bid and ask — contract is unquoted")

        # ── Expired ────────────────────────────────────────────────────
        if contract.expiration < self.today:
            reasons.append(f"expired: expiration {contract.expiration} is before today ({self.today})")

        # ── Liquidity ─────────────────────────────────────────────────
        if contract.volume < self.settings.min_option_volume:
            reasons.append(
                f"insufficient volume: {contract.volume} < {self.settings.min_option_volume}"
            )
        if contract.open_interest < self.settings.min_open_interest:
            reasons.append(
                f"insufficient open interest: {contract.open_interest} < {self.settings.min_open_interest}"
            )

        # ── Spread ────────────────────────────────────────────────────
        if contract.bid > 0 and contract.ask > 0:
            if contract.spread_pct > self.settings.max_bid_ask_spread_pct:
                reasons.append(
                    f"excessively wide spread: {contract.spread_pct:.1%} > "
                    f"{self.settings.max_bid_ask_spread_pct:.1%}"
                )

        # ── Stale quote ───────────────────────────────────────────────
        if quote_age_seconds is not None and quote_age_seconds > self.settings.stale_quote_seconds:
            reasons.append(
                f"stale quote: {quote_age_seconds:.0f}s old > {self.settings.stale_quote_seconds}s limit"
            )

        return len(reasons) == 0, reasons

    def filter_chain(
        self, chain: OptionChainSlice, *, quote_age_seconds: float | None = None
    ) -> tuple[OptionChainSlice, list[ContractRejection]]:
        """Returns (chain_of_only_valid_contracts, list_of_rejections_with_reasons).
        Never silently drops a contract without recording why."""
        valid: list[OptionContract] = []
        rejections: list[ContractRejection] = []

        for contract in chain.contracts:
            ok, reasons = self.validate(contract, quote_age_seconds=quote_age_seconds)
            if ok:
                valid.append(contract)
            else:
                rejections.append(ContractRejection(contract_symbol=contract.symbol, reasons=tuple(reasons)))

        return (
            OptionChainSlice(underlying=chain.underlying, fetched_at=chain.fetched_at, contracts=tuple(valid)),
            rejections,
        )
