"""
Structured logging (Milestone: Observability).

Every important pipeline step logs one of the EVENT_* constants below as
`extra={"event": ...}` so the dashboard/journal can filter on a stable
vocabulary instead of parsing free-text messages.
"""
from __future__ import annotations

import json
import logging
import sys
import typing
from datetime import UTC, datetime

# Canonical event names — the dashboard timeline renders these directly.
EVENT_MARKET_SCAN_STARTED = "MARKET_SCAN_STARTED"
EVENT_MARKET_SCAN_COMPLETED = "MARKET_SCAN_COMPLETED"
EVENT_OPPORTUNITY_FOUND = "OPPORTUNITY_FOUND"
EVENT_STRATEGY_SELECTED = "STRATEGY_SELECTED"
EVENT_TRADE_SCORED = "TRADE_SCORED"
EVENT_RISK_CHECK_STARTED = "RISK_CHECK_STARTED"
EVENT_RISK_APPROVED = "RISK_APPROVED"
EVENT_RISK_REJECTED = "RISK_REJECTED"
EVENT_ORDER_SUBMITTED = "ORDER_SUBMITTED"
EVENT_ORDER_FILLED = "ORDER_FILLED"
EVENT_ORDER_REJECTED = "ORDER_REJECTED"
EVENT_POSITION_OPENED = "POSITION_OPENED"
EVENT_EXIT_TRIGGERED = "EXIT_TRIGGERED"
EVENT_POSITION_CLOSED = "POSITION_CLOSED"
EVENT_EMERGENCY_HALT = "EMERGENCY_HALT"


class JsonFormatter(logging.Formatter):
    SECRET_KEYS: typing.ClassVar[set[str]] = {"api_key", "secret_key", "alpaca_api_key", "alpaca_secret_key"}

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        event = getattr(record, "event", None)
        if event:
            payload["event"] = event
        for key, value in getattr(record, "context", {}).items():
            if key.lower() in self.SECRET_KEYS:
                payload[key] = "***REDACTED***"
            else:
                payload[key] = value
        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO", fmt: str = "json") -> None:
    root = logging.getLogger("optionsentinel")
    root.setLevel(level)
    root.handlers.clear()

    handler = logging.StreamHandler(sys.stdout)
    if fmt == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root.addHandler(handler)
    root.propagate = False
