"""System-wide circuit breaker — independent of any single trade decision.

This is the backstop: even if every per-trade rule would pass, the
circuit breaker can force EMERGENCY_HALT based on account-wide state
(drawdown breach, daily loss breach, repeated risk rejections, or an
externally-flagged abnormal market condition).
"""
from __future__ import annotations

from core.config.settings import Settings

MAX_CONSECUTIVE_RISK_REJECTIONS = 5


class CircuitBreaker:
    def __init__(self, settings: Settings):
        self.settings = settings

    def check(self, portfolio) -> str | None:
        """Returns a halt reason string, or None if trading may continue."""
        if portfolio.abnormal_market_flag:
            return "abnormal market conditions flagged by upstream monitor"

        if portfolio.current_drawdown_pct >= self.settings.max_drawdown_pct:
            return (
                f"drawdown {portfolio.current_drawdown_pct:.2%} has reached the "
                f"{self.settings.max_drawdown_pct:.2%} hard limit"
            )

        daily_loss_floor = -abs(portfolio.equity * self.settings.max_daily_loss_pct)
        if portfolio.daily_pnl <= daily_loss_floor:
            return f"daily loss ${portfolio.daily_pnl:,.2f} breached the daily loss floor"

        if portfolio.consecutive_risk_rejections >= MAX_CONSECUTIVE_RISK_REJECTIONS:
            return (
                f"{portfolio.consecutive_risk_rejections} consecutive risk rejections — "
                "halting to force human review"
            )

        return None
