"""
These tests exercise AlpacaBrokerAdapter's MAPPING and REQUEST-CONSTRUCTION
logic — the part of Phase C that's actually at risk of bugs — using
hand-built stand-in objects shaped like Alpaca's documented responses.

They do NOT touch the network, do NOT require credentials, and do NOT
prove the real alpaca-py SDK behaves this way at runtime. That gap is
real and is called out explicitly in the Phase C report. What these
tests DO prove: given data shaped the way Alpaca's docs/examples say it
is shaped, our normalization code produces correct, safe OptionContract
objects, including for missing/partial/malformed data.
"""
from __future__ import annotations

from datetime import UTC, date, datetime
from types import SimpleNamespace

from core.models.options import OptionRight
from integrations.alpaca.adapter import AlpacaBrokerAdapter


def _fake_contract_meta(**overrides) -> SimpleNamespace:
    defaults = {
        "symbol": "AAPL240119C00100000",
        "underlying_symbol": "AAPL",
        "expiration_date": date(2024, 1, 19),
        "strike_price": "100",
        "type": "call",
        "open_interest": "6168",
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _fake_snapshot(**overrides) -> SimpleNamespace:
    quote = SimpleNamespace(bid_price=1.20, ask_price=1.30, timestamp=datetime.now(UTC))
    trade = SimpleNamespace(price=1.25, size=3)
    greeks = SimpleNamespace(delta=0.55, gamma=0.02, theta=-0.03, vega=0.10)
    defaults = {
        "symbol": "AAPL240119C00100000",
        "latest_quote": quote,
        "latest_trade": trade,
        "implied_volatility": 0.28,
        "greeks": greeks,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _adapter_instance() -> AlpacaBrokerAdapter:
    """Builds an AlpacaBrokerAdapter WITHOUT running __init__ (which would
    try to import/construct the real alpaca-py SDK). Only used to call
    instance methods whose logic doesn't depend on __init__ having run."""
    return object.__new__(AlpacaBrokerAdapter)


# ── 1. successful normalization ──────────────────────────────────────
def test_normalize_contract_full_data():
    meta = _fake_contract_meta()
    snap = _fake_snapshot()
    contract = AlpacaBrokerAdapter._normalize_contract("AAPL", meta, snap)

    assert contract.symbol == "AAPL240119C00100000"
    assert contract.underlying == "AAPL"
    assert contract.expiration == date(2024, 1, 19)
    assert contract.strike == 100.0
    assert contract.right == OptionRight.CALL
    assert contract.bid == 1.20
    assert contract.ask == 1.30
    assert contract.last == 1.25
    assert contract.volume == 3
    assert contract.open_interest == 6168
    assert contract.implied_volatility == 0.28
    assert contract.delta == 0.55
    assert contract.quote_timestamp is not None


# ── 2. missing data (no snapshot returned for this contract at all) ───
def test_normalize_contract_missing_snapshot_defaults_safely():
    meta = _fake_contract_meta()
    contract = AlpacaBrokerAdapter._normalize_contract("AAPL", meta, None)

    assert contract.bid == 0.0
    assert contract.ask == 0.0
    assert contract.last is None
    assert contract.volume == 0
    assert contract.implied_volatility is None
    assert contract.delta is None
    # Contract metadata (strike/expiration/OI) still populated even with no snapshot:
    assert contract.strike == 100.0
    assert contract.open_interest == 6168


def test_normalize_contract_snapshot_present_but_quote_missing():
    meta = _fake_contract_meta()
    snap = _fake_snapshot(latest_quote=None)
    contract = AlpacaBrokerAdapter._normalize_contract("AAPL", meta, snap)
    assert contract.bid == 0.0
    assert contract.ask == 0.0
    assert contract.last == 1.25  # trade data still present


# ── 3. malformed contracts ─────────────────────────────────────────────
def test_normalize_contract_malformed_open_interest_defaults_to_zero():
    meta = _fake_contract_meta(open_interest="")
    contract = AlpacaBrokerAdapter._normalize_contract("AAPL", meta, None)
    assert contract.open_interest == 0


def test_normalize_contract_none_open_interest_defaults_to_zero():
    meta = _fake_contract_meta(open_interest=None)
    contract = AlpacaBrokerAdapter._normalize_contract("AAPL", meta, None)
    assert contract.open_interest == 0


def test_normalize_contract_put_type():
    meta = _fake_contract_meta(type="put", symbol="AAPL240119P00100000")
    contract = AlpacaBrokerAdapter._normalize_contract("AAPL", meta, None)
    assert contract.right == OptionRight.PUT


def test_normalize_contract_string_expiration_date_is_parsed():
    """Defensive: if a future SDK version (or a raw_data=True response)
    returns expiration_date as a string instead of a date object."""
    meta = _fake_contract_meta(expiration_date="2024-01-19")
    contract = AlpacaBrokerAdapter._normalize_contract("AAPL", meta, None)
    assert contract.expiration == date(2024, 1, 19)


# ── 4/5. stale quotes / wide spreads — covered by tests/unit/test_options_validator.py
# against the *normalized* OptionContract; not re-duplicated here since the
# validator doesn't care whether the contract came from Alpaca or the mock adapter.


# ── 6. illiquid contracts (zero trade activity, snapshot present) ─────
def test_normalize_contract_zero_volume_and_oi_maps_correctly_not_crash():
    meta = _fake_contract_meta(open_interest="0")
    snap = _fake_snapshot(latest_trade=SimpleNamespace(price=1.25, size=0))
    contract = AlpacaBrokerAdapter._normalize_contract("AAPL", meta, snap)
    assert contract.volume == 0
    assert contract.open_interest == 0


# ── 7. API errors during snapshot fetch don't crash the whole chain ───
def test_get_option_chain_snapshot_fetch_failure_falls_back_gracefully():
    adapter = _adapter_instance()
    adapter.settings = SimpleNamespace(alpaca_env=SimpleNamespace(value="paper"))

    class FailingOptionData:
        def get_option_chain(self, req):
            raise RuntimeError("simulated API error")

    class FakeTrading:
        def get_option_contracts(self, req):
            return SimpleNamespace(option_contracts=[_fake_contract_meta()])

    adapter._trading = FakeTrading()
    adapter._option_data = FailingOptionData()

    chain = adapter.get_option_chain("AAPL", min_dte=14, max_dte=45)
    # Metadata still comes back; market data zeroed out rather than the whole call crashing.
    assert len(chain.contracts) == 1
    assert chain.contracts[0].bid == 0.0


# ── 8. empty chains ─────────────────────────────────────────────────────
def test_get_option_chain_returns_empty_slice_when_no_contracts():
    adapter = _adapter_instance()
    adapter.settings = SimpleNamespace(alpaca_env=SimpleNamespace(value="paper"))

    class FakeTrading:
        def get_option_contracts(self, req):
            return SimpleNamespace(option_contracts=[])

    adapter._trading = FakeTrading()
    adapter._option_data = None  # must not even be called

    chain = adapter.get_option_chain("AAPL", min_dte=14, max_dte=45)
    assert chain.contracts == ()
    assert chain.underlying == "AAPL"


# ── 9. full merge of metadata + snapshot dict (successful two-call path) ─
def test_get_option_chain_merges_metadata_and_snapshot_dict():
    adapter = _adapter_instance()
    adapter.settings = SimpleNamespace(alpaca_env=SimpleNamespace(value="paper"))

    meta1 = _fake_contract_meta(symbol="AAPL240119C00100000", strike_price="100")
    meta2 = _fake_contract_meta(symbol="AAPL240119C00105000", strike_price="105")
    snap1 = _fake_snapshot(symbol="AAPL240119C00100000")
    # meta2 intentionally has NO matching snapshot (simulates an inactive/no-quote contract)

    class FakeTrading:
        def get_option_contracts(self, req):
            return SimpleNamespace(option_contracts=[meta1, meta2])

    class FakeOptionData:
        def get_option_chain(self, req):
            return {"AAPL240119C00100000": snap1}  # dict keyed by symbol, as documented

    adapter._trading = FakeTrading()
    adapter._option_data = FakeOptionData()

    chain = adapter.get_option_chain("AAPL", min_dte=14, max_dte=45)
    assert len(chain.contracts) == 2
    by_symbol = {c.symbol: c for c in chain.contracts}
    assert by_symbol["AAPL240119C00100000"].bid == 1.20
    assert by_symbol["AAPL240119C00105000"].bid == 0.0  # no snapshot -> safe zeroed default


# ── 10. timestamp handling ──────────────────────────────────────────────
def test_normalized_contract_quote_timestamp_is_preserved():
    ts = datetime(2026, 1, 15, 14, 30, tzinfo=UTC)
    meta = _fake_contract_meta()
    snap = _fake_snapshot(latest_quote=SimpleNamespace(bid_price=1.0, ask_price=1.1, timestamp=ts))
    contract = AlpacaBrokerAdapter._normalize_contract("AAPL", meta, snap)
    assert contract.quote_timestamp == ts


# ── submit_order request construction (structural only — see caveats) ──
def test_submit_order_builds_mleg_request_with_correct_legs(monkeypatch):
    from core.models.options import OptionContract
    from core.models.trade import TradeLeg

    adapter = _adapter_instance()
    adapter.settings = SimpleNamespace(alpaca_env=SimpleNamespace(value="paper"))

    captured = {}

    class FakeTrading:
        def submit_order(self, request):
            captured["request"] = request
            return SimpleNamespace(
                id="order-123", client_order_id="cid-abc", status="accepted",
                filled_qty="0", submitted_at=datetime.now(UTC),
            )

    adapter._trading = FakeTrading()

    long_call = OptionContract(
        symbol="AAPL_LONG", underlying="AAPL", expiration=date(2026, 3, 1),
        strike=100, right=OptionRight.CALL, bid=5.0, ask=5.2, last=5.1, volume=10, open_interest=100,
    )
    short_call = OptionContract(
        symbol="AAPL_SHORT", underlying="AAPL", expiration=date(2026, 3, 1),
        strike=110, right=OptionRight.CALL, bid=2.0, ask=2.2, last=2.1, volume=10, open_interest=100,
    )
    legs = [TradeLeg(long_call, "BUY", 1), TradeLeg(short_call, "SELL", 1)]

    result = adapter.submit_order(legs=legs, quantity=1, client_order_id="cid-abc", limit_price=None)

    req = captured["request"]
    assert req.order_class.value == "mleg"
    assert len(req.legs) == 2
    assert req.legs[0].symbol == "AAPL_LONG"
    assert req.legs[0].side.value == "buy"
    assert req.legs[1].symbol == "AAPL_SHORT"
    assert req.legs[1].side.value == "sell"
    assert result.order_id == "order-123"
    assert result.status == "accepted"


def test_submit_order_refuses_live_endpoint_even_with_valid_request():
    adapter = _adapter_instance()
    adapter.settings = SimpleNamespace(alpaca_env=SimpleNamespace(value="live"))
    import pytest as _pytest  # local import: only needed for this one raises-check

    from integrations.alpaca.adapter import LiveTradingDisabledError

    with _pytest.raises(LiveTradingDisabledError):
        adapter.submit_order(legs=[], quantity=1, client_order_id="cid", limit_price=None)


def test_get_option_chain_fetches_all_metadata_pages():
    adapter = _adapter_instance()
    adapter.settings = SimpleNamespace(alpaca_env=SimpleNamespace(value="paper"))
    meta1 = _fake_contract_meta(symbol="AAPL240119C00100000")
    meta2 = _fake_contract_meta(symbol="AAPL240119P00100000", type="put")
    requests = []

    class FakeTrading:
        def get_option_contracts(self, request):
            requests.append(request)
            if len(requests) == 1:
                return SimpleNamespace(option_contracts=[meta1], next_page_token="second-page")
            return SimpleNamespace(option_contracts=[meta2], next_page_token=None)

    class FakeOptionData:
        def get_option_chain(self, request):
            return {}

    adapter._trading = FakeTrading()
    adapter._option_data = FakeOptionData()

    chain = adapter.get_option_chain("AAPL", min_dte=14, max_dte=45)

    assert len(chain.contracts) == 2
    assert requests[0].limit == 10000
    assert requests[1].page_token == "second-page"


def test_submit_order_builds_single_leg_market_order():
    adapter = _adapter_instance()
    adapter.settings = SimpleNamespace(alpaca_env=SimpleNamespace(value="paper"))
    captured = {}

    class FakeTrading:
        def submit_order(self, request):
            captured["request"] = request
            return SimpleNamespace(
                id="order-456", client_order_id="cid-single", status="accepted",
                filled_qty="0", submitted_at=datetime.now(UTC),
            )

    adapter._trading = FakeTrading()
    result = adapter.submit_order(
        legs=[{"symbol": "AAPL260301C00100000", "side": "buy", "quantity": 2}],
        quantity=3,
        client_order_id="cid-single",
        limit_price=None,
    )

    assert captured["request"].symbol == "AAPL260301C00100000"
    assert captured["request"].side.value == "buy"
    assert captured["request"].qty == 6
    assert result.status == "accepted"
    assert result.raw == {"order_class": "SINGLE", "legs": 1}


def test_submit_order_returns_rejection_when_request_fails():
    adapter = _adapter_instance()
    adapter.settings = SimpleNamespace(alpaca_env=SimpleNamespace(value="paper"))

    result = adapter.submit_order(legs=[], quantity=1, client_order_id="cid-fail", limit_price=None)

    assert result.status == "rejected"
    assert result.order_id == ""
    assert result.client_order_id == "cid-fail"
