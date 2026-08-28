"""
These tests hit the real Alpaca paper API and are skipped automatically
unless ALPACA_API_KEY/ALPACA_SECRET_KEY are set in the environment.
Run with: pytest tests/integration -v
(requires `pip install -e .` so alpaca-py is available)
"""
from __future__ import annotations

import pytest

from core.config.settings import Settings


def needs_credentials(settings: Settings) -> bool:
    return not (settings.alpaca_api_key and settings.alpaca_secret_key)


@pytest.fixture
def live_settings() -> Settings:
    return Settings()


def test_account_retrieval_succeeds(live_settings):
    if needs_credentials(live_settings):
        pytest.skip("ALPACA_API_KEY/ALPACA_SECRET_KEY not configured")
    from integrations.alpaca.adapter import AlpacaBrokerAdapter

    adapter = AlpacaBrokerAdapter(live_settings)
    account = adapter.get_account()
    assert account.equity > 0
    assert account.is_paper is True


def test_market_data_retrieval_succeeds(live_settings):
    if needs_credentials(live_settings):
        pytest.skip("ALPACA_API_KEY/ALPACA_SECRET_KEY not configured")
    from integrations.alpaca.adapter import AlpacaBrokerAdapter

    adapter = AlpacaBrokerAdapter(live_settings)
    bars = adapter.get_price_bars("SPY", lookback_days=10)
    assert len(bars) > 0


def test_invalid_credentials_fail_cleanly(live_settings):
    if needs_credentials(live_settings):
        pytest.skip("ALPACA_API_KEY/ALPACA_SECRET_KEY not configured — cannot test invalid-vs-valid contrast")
    from integrations.alpaca.adapter import AlpacaBrokerAdapter

    bad_settings = live_settings.model_copy(update={"alpaca_api_key": "invalid", "alpaca_secret_key": "invalid"})
    adapter = AlpacaBrokerAdapter(bad_settings)
    status = adapter.health_check()
    assert status["ALPACA_CONNECTION"].startswith("FAIL")


def test_live_env_without_confirmation_flag_raises():
    """This must pass with NO credentials at all — it's a pure safety-gate test."""
    from integrations.alpaca.adapter import AlpacaBrokerAdapter, LiveTradingDisabledError

    unsafe_settings = Settings(alpaca_env="live", alpaca_live_trading_confirmed=False)
    with pytest.raises(LiveTradingDisabledError):
        AlpacaBrokerAdapter(unsafe_settings)
