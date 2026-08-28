"""Position sizing helpers used by the Risk Sentinel to answer:
"if we cannot approve the full requested quantity, what quantity (if any)
clears every size-sensitive limit?"
"""
from __future__ import annotations

from core.config.settings import Settings


def max_affordable_quantity(req, settings: Settings) -> int:
    """Returns the largest integer quantity (>= 0) that satisfies buying
    power, max trade risk, max portfolio risk, and concentration limits
    simultaneously. 0 means the trade cannot be sized down into safety —
    treat as REJECT."""
    per_contract_risk = abs(req.candidate.max_loss)
    if per_contract_risk <= 0:
        return 0

    limits = []

    # Buying power
    limits.append(int(req.portfolio.buying_power // per_contract_risk))

    # Max trade risk
    trade_risk_cap = req.portfolio.equity * settings.max_trade_risk_pct
    limits.append(int(trade_risk_cap // per_contract_risk))

    # Max portfolio risk (room remaining after existing open risk)
    portfolio_cap = req.portfolio.equity * settings.max_portfolio_risk_pct
    remaining_portfolio_room = max(0.0, portfolio_cap - req.portfolio.total_open_risk_capital)
    limits.append(int(remaining_portfolio_room // per_contract_risk))

    # Concentration cap for this symbol
    same_symbol_risk = sum(
        p.risk_capital for p in req.portfolio.open_positions if p.symbol == req.candidate.symbol
    )
    concentration_cap = req.portfolio.equity * settings.max_position_concentration_pct
    remaining_concentration_room = max(0.0, concentration_cap - same_symbol_risk)
    limits.append(int(remaining_concentration_room // per_contract_risk))

    capped = min(limits + [req.proposed_quantity])
    return max(0, capped)
