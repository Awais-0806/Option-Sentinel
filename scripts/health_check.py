"""
Usage:  python -m scripts.health_check

Reports Alpaca connectivity, environment, account, market-data, and
options-data status, plus Alpaca CLI presence. Never raises past main()
without printing a clear message first — a health check that crashes
opaquely isn't a health check.

Adapter selection goes through integrations/broker_factory.py, the same
single source of truth apps/api/main.py uses — keyed on EXECUTION_MODE,
not on whether credential strings happen to be non-empty.
"""
from __future__ import annotations

import sys

from core.config.settings import get_settings
from core.events.logging_config import configure_logging
from integrations.alpaca_cli.cli import cli_health_check
from integrations.broker_factory import BrokerConfigurationError, get_broker_adapter

MOCK_MODES = ("DRY_RUN", "PAPER_SIMULATION")


def main() -> int:
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_format)

    print("=== OptionSentinel Health Check ===")
    print(f"DEPLOY_STAGE:     {settings.deploy_stage.value}")
    print(f"EXECUTION_MODE:   {settings.execution_mode.value}")
    print(f"ALPACA_ENV:       {settings.alpaca_env.value}")

    try:
        adapter = get_broker_adapter(settings)
    except BrokerConfigurationError as exc:
        print(f"\nOVERALL: FAIL (configuration)\nREASON: {exc}")
        return 1
    except Exception as exc:  # noqa: BLE001 - a broken adapter init must still print, not crash
        print(f"\nOVERALL: FAIL (adapter init)\nREASON: {exc}")
        return 1

    is_mock = settings.execution_mode.value in MOCK_MODES
    source = "MOCK (DRY_RUN / PAPER_SIMULATION — no network calls made)" if is_mock else "REAL (alpaca-py, paper endpoint)"
    print(f"DATA SOURCE:      {source}\n")

    status = adapter.health_check()
    for key in ("ALPACA_CONNECTION", "ENVIRONMENT", "ACCOUNT", "MARKET_DATA", "OPTIONS_DATA"):
        print(f"{key}: {status.get(key, 'UNKNOWN')}")

    print("\n=== Alpaca CLI ===")
    cli_status = cli_health_check()
    for key, value in cli_status.items():
        print(f"{key}: {value}")

    any_fail = any(str(v).startswith("FAIL") for v in status.values())
    print("\nOVERALL:", "FAIL" if any_fail else "OK")
    return 1 if any_fail else 0


if __name__ == "__main__":
    sys.exit(main())
