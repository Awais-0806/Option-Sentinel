"""
Day-1 regression suite for the "/pipeline/run returns 500 in DRY_RUN" bug.

Root cause was apps/api/main.py picking the real Alpaca adapter whenever
credential *strings* were non-empty — true even for the placeholder
values shipped in .env.example. These tests pin the fix: adapter
selection must depend ONLY on execution_mode.
"""
from __future__ import annotations

import pytest

from core.config.settings import AlpacaEnv, ExecutionMode, Settings
from integrations.alpaca.adapter import LiveTradingDisabledError
from integrations.alpaca.mock_adapter import MockBrokerAdapter
from integrations.broker_factory import BrokerConfigurationError, get_broker_adapter


def test_dry_run_never_selects_real_adapter_even_with_credentials_present():
    """The exact regression: real-looking credentials must NOT flip DRY_RUN
    to the real adapter. Only execution_mode controls this."""
    settings = Settings(
        execution_mode=ExecutionMode.DRY_RUN,
        alpaca_api_key="PKREALLOOKINGKEY123",
        alpaca_secret_key="realsecretlookingvalue456",
    )
    adapter = get_broker_adapter(settings)
    assert isinstance(adapter, MockBrokerAdapter)


def test_dry_run_with_placeholder_credentials_still_uses_mock(settings):
    """The literal shipped .env.example scenario the human tester hit."""
    settings.execution_mode = ExecutionMode.DRY_RUN
    settings.alpaca_api_key = "your_paper_api_key_here"
    settings.alpaca_secret_key = "your_paper_secret_key_here"
    adapter = get_broker_adapter(settings)
    assert isinstance(adapter, MockBrokerAdapter)


def test_paper_simulation_also_uses_mock_regardless_of_credentials():
    settings = Settings(
        execution_mode=ExecutionMode.PAPER_SIMULATION,
        alpaca_api_key="PKREALLOOKINGKEY123",
        alpaca_secret_key="realsecretlookingvalue456",
    )
    adapter = get_broker_adapter(settings)
    assert isinstance(adapter, MockBrokerAdapter)


def test_paper_manual_approval_without_credentials_raises_clean_config_error(settings):
    settings.execution_mode = ExecutionMode.PAPER_MANUAL_APPROVAL
    settings.alpaca_api_key = ""
    settings.alpaca_secret_key = ""
    with pytest.raises(BrokerConfigurationError):
        get_broker_adapter(settings)


def test_paper_autonomous_with_placeholder_credentials_raises_clean_config_error(settings):
    settings.execution_mode = ExecutionMode.PAPER_AUTONOMOUS
    settings.alpaca_api_key = "your_paper_api_key_here"
    settings.alpaca_secret_key = "your_paper_secret_key_here"
    with pytest.raises(BrokerConfigurationError):
        get_broker_adapter(settings)


def test_paper_mode_with_live_endpoint_is_rejected(settings):
    """Defense in depth: PAPER_* execution modes must refuse to run against
    a live Alpaca endpoint even if ALPACA_ENV was mis-set."""
    settings.execution_mode = ExecutionMode.PAPER_AUTONOMOUS
    settings.alpaca_env = AlpacaEnv.LIVE
    settings.alpaca_api_key = "PKREALLOOKINGKEY123"
    settings.alpaca_secret_key = "realsecretlookingvalue456"
    with pytest.raises(BrokerConfigurationError):
        get_broker_adapter(settings)


def test_live_execution_mode_is_always_hard_blocked(settings):
    """Absolute safety rule: ExecutionMode.LIVE never succeeds, regardless
    of any credential or confirmation flag."""
    settings.execution_mode = ExecutionMode.LIVE
    settings.alpaca_env = AlpacaEnv.LIVE
    settings.alpaca_live_trading_confirmed = True
    settings.alpaca_api_key = "PKREALLOOKINGKEY123"
    settings.alpaca_secret_key = "realsecretlookingvalue456"
    with pytest.raises(LiveTradingDisabledError):
        get_broker_adapter(settings)
