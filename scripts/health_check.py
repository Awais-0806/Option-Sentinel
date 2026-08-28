"""
Usage:  python -m scripts.health_check

Reports Alpaca connectivity, environment, account, market-data, and
options-data status, plus Alpaca CLI presence. Never raises on its own —
a health check that crashes isn't a health check.

If no ALPACA_API_KEY/ALPACA_SECRET_KEY are configured, falls back to the
mock adapter automatically so `python -m scripts.health_check` is
runnable immediately after cloning the repo, before any credentials
exist.
"""
from __future__ import annotations

import sys

from core.config.settings import get_settings
from core.events.logging_config import configure_logging
from integrations.alpaca_cli.cli import cli_health_check


def main() -> int:
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_format)

    print("=== OptionSentinel Health Check ===")
    print(f"DEPLOY_STAGE:     {settings.deploy_stage.value}")
    print(f"EXECUTION_MODE:   {settings.execution_mode.value}")
    print(f"ALPACA_ENV:       {settings.alpaca_env.value}")

    have_creds = bool(settings.alpaca_api_key and settings.alpaca_secret_key)

    if have_creds:
        try:
            from integrations.alpaca.adapter import AlpacaBrokerAdapter
            adapter = AlpacaBrokerAdapter(settings)
            source = "REAL (alpaca-py)"
        except Exception as exc:  # noqa: BLE001
            print(f"WARNING: could not initialize real Alpaca adapter ({exc}); falling back to mock.")
            from integrations.alpaca.mock_adapter import MockBrokerAdapter
            adapter = MockBrokerAdapter(settings)
            source = "MOCK (fallback — real adapter failed to init)"
    else:
        from integrations.alpaca.mock_adapter import MockBrokerAdapter
        adapter = MockBrokerAdapter(settings)
        source = "MOCK (no ALPACA_API_KEY/ALPACA_SECRET_KEY configured)"

    print(f"ADAPTER SOURCE:   {source}\n")

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
