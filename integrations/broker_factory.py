"""
Broker adapter factory — single source of truth for real-vs-mock
selection.

Day-1 bug (fixed here): apps/api/main.py used to decide "real adapter if
credentials are present" instead of asking what execution mode the
operator configured. Since .env.example ships with non-empty *placeholder*
credential strings, that check was almost always true, so DRY_RUN would
silently try to hit the real Alpaca API with garbage keys and 500.

The fix: adapter selection is keyed ONLY on Settings.execution_mode, per
this table:

    DRY_RUN                -> MockBrokerAdapter
    PAPER_SIMULATION       -> MockBrokerAdapter (reserved seam for a future
                               dedicated simulation adapter)
    PAPER_MANUAL_APPROVAL  -> AlpacaBrokerAdapter (real, paper endpoint)
    PAPER_AUTONOMOUS       -> AlpacaBrokerAdapter (real, paper endpoint)
    LIVE                   -> hard blocked, always, no exceptions

Every caller (apps/api/main.py, scripts/health_check.py, any future CLI
entry point) MUST go through get_broker_adapter() rather than
constructing an adapter directly, or this bug class can reappear.
"""
from __future__ import annotations

from core.config.settings import AlpacaEnv, ExecutionMode, Settings
from core.interfaces.broker import BrokerAdapter


class BrokerConfigurationError(RuntimeError):
    """Raised when the configured execution mode requires something
    (credentials, an unblocked endpoint) that isn't available. This is a
    configuration problem, not a trading decision — callers should
    surface it as a clear 4xx-style error, not let it crash as a raw 500."""


def get_broker_adapter(settings: Settings) -> BrokerAdapter:
    mode = settings.execution_mode

    if mode in (ExecutionMode.DRY_RUN, ExecutionMode.PAPER_SIMULATION):
        from integrations.alpaca.mock_adapter import MockBrokerAdapter
        return MockBrokerAdapter(settings)

    if mode in (ExecutionMode.PAPER_MANUAL_APPROVAL, ExecutionMode.PAPER_AUTONOMOUS):
        if settings.alpaca_env != AlpacaEnv.PAPER:
            raise BrokerConfigurationError(
                f"{mode.value} requires ALPACA_ENV=paper, got '{settings.alpaca_env.value}'."
            )
        if not (settings.alpaca_api_key and settings.alpaca_secret_key):
            raise BrokerConfigurationError(
                f"{mode.value} requires APCA_API_KEY_ID/APCA_API_SECRET_KEY (or legacy "
                "ALPACA_API_KEY/ALPACA_SECRET_KEY) to be set to real paper credentials in "
                ".env. Switch EXECUTION_MODE back to DRY_RUN to run without credentials."
            )
        placeholder_markers = ("your_paper_api_key_here", "your_paper_secret_key_here")
        if settings.alpaca_api_key in placeholder_markers or settings.alpaca_secret_key in placeholder_markers:
            raise BrokerConfigurationError(
                f"{mode.value} is configured but APCA_API_KEY_ID/APCA_API_SECRET_KEY (or "
                "legacy ALPACA_API_KEY/ALPACA_SECRET_KEY) still contain the placeholder values "
                "from .env.example. Replace them with real Alpaca paper credentials, or switch "
                "EXECUTION_MODE back to DRY_RUN."
            )
        from integrations.alpaca.adapter import AlpacaBrokerAdapter
        return AlpacaBrokerAdapter(settings)

    if mode == ExecutionMode.LIVE:
        from integrations.alpaca.adapter import LiveTradingDisabledError
        raise LiveTradingDisabledError(
            "ExecutionMode.LIVE is hard-blocked in this build, unconditionally. "
            "There is no configuration that enables it — see docs/ARCHITECTURE.md, "
            "'Safety gates'."
        )

    raise BrokerConfigurationError(f"Unknown execution mode: {mode!r}")
