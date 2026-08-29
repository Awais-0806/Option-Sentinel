from __future__ import annotations

from datetime import date, timedelta

from core.models.options import OptionChainSlice, OptionContract, OptionRight
from agents.options_analyst.validator import OptionContractValidator


def _contract(**overrides) -> OptionContract:
    defaults = dict(
        symbol="TEST250101C00100000", underlying="TEST", expiration=date.today() + timedelta(days=30),
        strike=100.0, right=OptionRight.CALL, bid=1.0, ask=1.1, last=1.05, volume=100, open_interest=500,
    )
    defaults.update(overrides)
    return OptionContract(**defaults)


def test_clean_contract_passes(settings):
    ok, reasons = OptionContractValidator(settings).validate(_contract())
    assert ok
    assert reasons == []


def test_impossible_strike_is_rejected(settings):
    ok, reasons = OptionContractValidator(settings).validate(_contract(strike=0))
    assert not ok
    assert any("impossible strike" in r for r in reasons)


def test_expired_contract_is_rejected(settings):
    ok, reasons = OptionContractValidator(settings).validate(
        _contract(expiration=date.today() - timedelta(days=1))
    )
    assert not ok
    assert any("expired" in r for r in reasons)


def test_crossed_quote_is_rejected(settings):
    ok, reasons = OptionContractValidator(settings).validate(_contract(bid=5.0, ask=4.0))
    assert not ok
    assert any("crossed quote" in r for r in reasons)


def test_zero_bid_ask_is_rejected(settings):
    ok, reasons = OptionContractValidator(settings).validate(_contract(bid=0.0, ask=0.0))
    assert not ok
    assert any("unquoted" in r for r in reasons)


def test_negative_bid_is_rejected(settings):
    ok, reasons = OptionContractValidator(settings).validate(_contract(bid=-1.0, ask=1.0))
    assert not ok
    assert any("negative bid/ask" in r for r in reasons)


def test_insufficient_volume_is_rejected(settings):
    ok, reasons = OptionContractValidator(settings).validate(_contract(volume=0))
    assert not ok
    assert any("insufficient volume" in r for r in reasons)


def test_insufficient_open_interest_is_rejected(settings):
    ok, reasons = OptionContractValidator(settings).validate(_contract(open_interest=0))
    assert not ok
    assert any("insufficient open interest" in r for r in reasons)


def test_excessively_wide_spread_is_rejected(settings):
    # settings.max_bid_ask_spread_pct defaults to 0.12 (12%)
    ok, reasons = OptionContractValidator(settings).validate(_contract(bid=1.0, ask=2.0))
    assert not ok
    assert any("wide spread" in r for r in reasons)


def test_stale_quote_is_rejected(settings):
    # settings.stale_quote_seconds defaults to 60
    ok, reasons = OptionContractValidator(settings).validate(_contract(), quote_age_seconds=999)
    assert not ok
    assert any("stale quote" in r for r in reasons)


def test_stale_quote_detected_from_contracts_own_timestamp(settings):
    """Real Alpaca contracts carry their own quote_timestamp; the validator
    must use it directly without the caller needing to pass quote_age_seconds."""
    from datetime import datetime, timedelta, timezone

    old_timestamp = datetime.now(timezone.utc) - timedelta(hours=2)
    ok, reasons = OptionContractValidator(settings).validate(_contract(quote_timestamp=old_timestamp))
    assert not ok
    assert any("stale quote" in r for r in reasons)


def test_fresh_contract_timestamp_is_not_flagged_stale(settings):
    from datetime import datetime, timezone

    fresh = datetime.now(timezone.utc)
    ok, reasons = OptionContractValidator(settings).validate(_contract(quote_timestamp=fresh))
    assert ok
    assert reasons == []


def test_contract_can_have_multiple_simultaneous_rejection_reasons(settings):
    ok, reasons = OptionContractValidator(settings).validate(
        _contract(volume=0, open_interest=0, bid=0.0, ask=0.0)
    )
    assert not ok
    assert len(reasons) >= 2  # every failure reported, not just the first


def test_filter_chain_separates_valid_from_rejected_with_reasons(settings):
    good = _contract(symbol="GOOD")
    bad = _contract(symbol="BAD", volume=0, open_interest=0)
    chain = OptionChainSlice(underlying="TEST", fetched_at="now", contracts=(good, bad))

    filtered, rejections = OptionContractValidator(settings).filter_chain(chain)

    assert len(filtered.contracts) == 1
    assert filtered.contracts[0].symbol == "GOOD"
    assert len(rejections) == 1
    assert rejections[0].contract_symbol == "BAD"
    assert len(rejections[0].reasons) >= 1  # every rejection carries a reason, never silent
