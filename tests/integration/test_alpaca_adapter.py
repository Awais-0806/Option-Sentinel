"""
These tests hit the real Alpaca paper API and are skipped automatically
unless ALPACA_API_KEY/ALPACA_SECRET_KEY are set in the environment.
Run with: pytest tests/integration -v
(requires `pip install -e .` so alpaca-py is available)

ORDER-SUBMISSION SAFETY: no test in this file submits a real order unless
the operator BOTH configures real paper credentials AND explicitly sets
OPTIONSENTINEL_ALLOW_ORDER_TEST=1 in the environment for that run. Neither
credentials alone nor EXECUTION_MODE alone can trigger an order submission
from this test file — that is a deliberate second, independent gate on
top of the ones in integrations/broker_factory.py and
core/orchestration/pipeline.py.
"""
from __future__ import annotations

import os

import pytest

from core.config.settings import Settings


def needs_credentials(settings: Settings) -> bool:
    return not (settings.alpaca_api_key and settings.alpaca_secret_key)


def order_test_explicitly_allowed() -> bool:
    return os.environ.get("OPTIONSENTINEL_ALLOW_ORDER_TEST") == "1"


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


# ── Phase C: real options data ──────────────────────────────────────────

def test_option_chain_retrieval_succeeds(live_settings):
    if needs_credentials(live_settings):
        pytest.skip("ALPACA_API_KEY/ALPACA_SECRET_KEY not configured")
    from integrations.alpaca.adapter import AlpacaBrokerAdapter

    adapter = AlpacaBrokerAdapter(live_settings)
    chain = adapter.get_option_chain("SPY", min_dte=14, max_dte=45)
    assert chain.underlying == "SPY"
    assert len(chain.contracts) > 0, "SPY should always have active listed contracts in this DTE window"
    sample = chain.contracts[0]
    assert sample.strike > 0
    assert sample.expiration is not None
    print(f"\n[integration] fetched {len(chain.contracts)} real SPY contracts; "
          f"sample: {sample.symbol} strike={sample.strike} bid={sample.bid} ask={sample.ask} "
          f"OI={sample.open_interest} IV={sample.implied_volatility} quote_ts={sample.quote_timestamp}")


def test_option_chain_contracts_pass_through_the_validator(live_settings):
    """End-to-end: real Alpaca data -> our validator -> mostly-clean results.
    This does NOT assert zero rejections (real chains legitimately contain
    illiquid/wide-spread contracts) — it asserts the pipeline handles real
    data without crashing and every rejection carries a reason."""
    if needs_credentials(live_settings):
        pytest.skip("ALPACA_API_KEY/ALPACA_SECRET_KEY not configured")
    from agents.options_analyst.validator import OptionContractValidator
    from integrations.alpaca.adapter import AlpacaBrokerAdapter

    adapter = AlpacaBrokerAdapter(live_settings)
    chain = adapter.get_option_chain("SPY", min_dte=14, max_dte=45)
    validator = OptionContractValidator(live_settings)
    filtered, rejections = validator.filter_chain(chain)

    assert len(filtered.contracts) + len(rejections) == len(chain.contracts)
    for rejection in rejections:
        assert len(rejection.reasons) >= 1, "every rejection must carry at least one reason"
    print(f"\n[integration] {len(filtered.contracts)} passed validation, "
          f"{len(rejections)} rejected out of {len(chain.contracts)} total")


def test_option_chain_for_illiquid_or_unlisted_underlying_does_not_crash(live_settings):
    """Empty-chain handling against the real API (Phase L requirement #8)."""
    if needs_credentials(live_settings):
        pytest.skip("ALPACA_API_KEY/ALPACA_SECRET_KEY not configured")
    from integrations.alpaca.adapter import AlpacaBrokerAdapter

    adapter = AlpacaBrokerAdapter(live_settings)
    # A symbol vanishingly unlikely to have listed options; if Alpaca ever
    # does list one, the assertion below still just checks "didn't crash."
    chain = adapter.get_option_chain("ZZZZTESTNOTREAL", min_dte=14, max_dte=45)
    assert chain.contracts == () or len(chain.contracts) >= 0  # must not raise


# ── Order submission — requires a SECOND, explicit opt-in beyond credentials ──

def test_order_submission_is_gated_behind_explicit_manual_flag(live_settings):
    """This test intentionally does NOT submit an order by default, even
    with valid credentials. It only documents/exercises the gate itself."""
    if not order_test_explicitly_allowed():
        pytest.skip(
            "Order-submission testing requires OPTIONSENTINEL_ALLOW_ORDER_TEST=1 "
            "in the environment, in addition to real credentials. Not set — skipping "
            "by design. See 'PAPER TRADING TEST' instructions in the Phase C report."
        )
    if needs_credentials(live_settings):
        pytest.skip("ALPACA_API_KEY/ALPACA_SECRET_KEY not configured")
    pytest.skip(
        "Manual order-submission test intentionally left as a documented seam, not "
        "auto-implemented — Phase E (manual approval flow) must exist first per the "
        "explicit instruction to not proceed to autonomous/manual execution testing "
        "in this phase."
    )
