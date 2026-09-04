"""
Concrete BrokerAdapter backed by Alpaca's paper trading API via alpaca-py.

Hard safety gate: this adapter refuses to construct against a live
endpoint unless Settings.is_live_trading_permitted is True (both
ALPACA_ENV=live and ALPACA_LIVE_TRADING_CONFIRMED=true). Day 1 of this
build does not implement any live order path at all — REJECTED even if
someone flips both flags, until that code is explicitly written and
reviewed.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone

from core.config.settings import Settings
from core.interfaces.broker import AccountSnapshot, BrokerPosition, OrderResult
from core.models.market import PriceBar
from core.models.options import OptionChainSlice, OptionRight

logger = logging.getLogger("optionsentinel.integrations.alpaca")


class LiveTradingDisabledError(RuntimeError):
    """Raised whenever anything tries to route an order at a live endpoint."""


class AlpacaBrokerAdapter:
    """
    Thin wrapper. Import of `alpaca` SDK is deferred into __init__ so that
    the rest of the codebase (and its tests) can run without the package
    installed when only DRY_RUN / mock mode is needed.
    """

    def __init__(self, settings: Settings):
        self.settings = settings

        if settings.alpaca_env.value != "paper":
            raise LiveTradingDisabledError(
                "Live Alpaca access is disabled in this build. Set ALPACA_ENV=paper."
            )

        try:
            from alpaca.trading.client import TradingClient
            from alpaca.data.historical.stock import StockHistoricalDataClient
            from alpaca.data.historical.option import OptionHistoricalDataClient
        except ImportError as exc:  # pragma: no cover - exercised only without the dep installed
            raise ImportError(
                "alpaca-py is not installed. Run `pip install -e .` "
                "(see pyproject.toml) or use the mock adapter for offline development."
            ) from exc

        self._trading = TradingClient(
            api_key=settings.alpaca_api_key,
            secret_key=settings.alpaca_secret_key,
            paper=True,
        )
        self._stock_data = StockHistoricalDataClient(
            api_key=settings.alpaca_api_key, secret_key=settings.alpaca_secret_key
        )
        self._option_data = OptionHistoricalDataClient(
            api_key=settings.alpaca_api_key, secret_key=settings.alpaca_secret_key
        )

    # ── Account / positions ──────────────────────────────────────────
    def get_account(self) -> AccountSnapshot:
        acct = self._trading.get_account()
        equity = float(acct.equity)
        last_equity = float(acct.last_equity) if acct.last_equity else equity
        return AccountSnapshot(
            equity=equity,
            buying_power=float(acct.buying_power),
            cash=float(acct.cash),
            daily_pnl=equity - last_equity,
            peak_equity=max(equity, last_equity),  # true peak should come from the P&L history table
            is_paper=self.settings.alpaca_env.value == "paper",
        )

    def get_positions(self) -> list[BrokerPosition]:
        positions = self._trading.get_all_positions()
        return [
            BrokerPosition(
                symbol=p.symbol,
                strategy_hint=None,
                quantity=int(float(p.qty)),
                market_value=float(p.market_value),
                unrealized_pl=float(p.unrealized_pl),
            )
            for p in positions
        ]

    # ── Market data ───────────────────────────────────────────────────
    def get_price_bars(self, symbol: str, lookback_days: int) -> list[PriceBar]:
        from alpaca.data.requests import StockBarsRequest
        from alpaca.data.timeframe import TimeFrame

        req = StockBarsRequest(
            symbol_or_symbols=symbol,
            timeframe=TimeFrame.Day,
            start=datetime.now(timezone.utc) - timedelta(days=lookback_days * 2),  # buffer for weekends/holidays
        )
        bars = self._stock_data.get_stock_bars(req)
        rows = bars[symbol] if symbol in bars.data else []
        return [
            PriceBar(timestamp=b.timestamp, open=b.open, high=b.high, low=b.low, close=b.close, volume=b.volume)
            for b in rows[-lookback_days:]
        ]

    def get_option_chain(
        self,
        symbol: str,
        min_dte: int,
        max_dte: int,
        option_type: str | OptionRight | None = None,
    ) -> OptionChainSlice:
        """Fetch active Alpaca option contracts and their latest snapshots."""
        from alpaca.data.enums import OptionsFeed
        from alpaca.data.requests import OptionChainRequest
        from alpaca.trading.enums import AssetStatus, ContractType
        from alpaca.trading.requests import GetOptionContractsRequest

        today = date.today()
        exp_gte = today + timedelta(days=min_dte)
        exp_lte = today + timedelta(days=max_dte)
        fetched_at = datetime.now(timezone.utc).isoformat()

        try:
            option_contracts = []
            page_token = None
            while True:
                request_kwargs = {
                    "underlying_symbols": [symbol],
                    "status": AssetStatus.ACTIVE,
                    "expiration_date_gte": exp_gte,
                    "expiration_date_lte": exp_lte,
                    "limit": 10000,
                }
                if option_type is not None:
                    requested_type = str(getattr(option_type, "value", option_type)).lower()
                    request_kwargs["type"] = ContractType(requested_type)
                if page_token:
                    request_kwargs["page_token"] = page_token

                contracts_resp = self._trading.get_option_contracts(
                    GetOptionContractsRequest(**request_kwargs)
                )
                option_contracts.extend(getattr(contracts_resp, "option_contracts", []) or [])
                page_token = getattr(contracts_resp, "next_page_token", None)
                if not page_token:
                    break
        except Exception as exc:  # noqa: BLE001 - market data failure must not stop the pipeline
            logger.warning("option contract fetch failed for %s: %s", symbol, exc)
            return OptionChainSlice(underlying=symbol, fetched_at=fetched_at, contracts=())

        if not option_contracts:
            return OptionChainSlice(underlying=symbol, fetched_at=fetched_at, contracts=())

        chain_req = OptionChainRequest(
            underlying_symbol=symbol,
            feed=OptionsFeed.INDICATIVE,
            expiration_date_gte=exp_gte,
            expiration_date_lte=exp_lte,
        )
        try:
            snapshots = self._option_data.get_option_chain(chain_req)
        except Exception as exc:  # noqa: BLE001 - snapshot failure must not stop the pipeline
            logger.warning("option snapshot fetch failed for %s: %s", symbol, exc)
            snapshots = {}

        contracts = tuple(
            self._normalize_contract(symbol, meta, snapshots.get(meta.symbol))
            for meta in option_contracts
        )
        return OptionChainSlice(underlying=symbol, fetched_at=fetched_at, contracts=contracts)

    @staticmethod
    def _normalize_contract(underlying: str, meta, snapshot) -> "OptionContract":
        """Maps one Alpaca contract-metadata object + its (possibly missing)
        snapshot into our normalized OptionContract. Isolated as a
        @staticmethod specifically so it's unit-testable with hand-built
        fake objects, without needing a real TradingClient/alpaca-py at all."""
        from core.models.options import OptionContract

        quote = getattr(snapshot, "latest_quote", None) if snapshot else None
        trade = getattr(snapshot, "latest_trade", None) if snapshot else None
        greeks = getattr(snapshot, "greeks", None) if snapshot else None
        implied_vol = getattr(snapshot, "implied_volatility", None) if snapshot else None

        raw_type = str(getattr(meta, "type", "")).lower()
        right = OptionRight.CALL if "call" in raw_type else OptionRight.PUT

        raw_oi = getattr(meta, "open_interest", None)
        try:
            open_interest = int(raw_oi) if raw_oi not in (None, "") else 0
        except (TypeError, ValueError):
            open_interest = 0

        bid = getattr(quote, "bid_price", None) if quote else None
        ask = getattr(quote, "ask_price", None) if quote else None
        last_price = getattr(trade, "price", None) if trade else None
        quote_timestamp = getattr(quote, "timestamp", None) if quote else None

        return OptionContract(
            symbol=meta.symbol,
            underlying=underlying,
            expiration=meta.expiration_date if hasattr(meta.expiration_date, "year") else date.fromisoformat(str(meta.expiration_date)),
            strike=float(meta.strike_price),
            right=right,
            bid=float(bid) if bid is not None else 0.0,
            ask=float(ask) if ask is not None else 0.0,
            last=float(last_price) if last_price is not None else None,
            # CAVEAT (see Phase C report): mapped from latest_trade.size, which is the
            # size of the single most recent print, NOT cumulative daily volume. Alpaca's
            # options snapshot endpoint does not clearly expose a cumulative-daily-volume
            # field distinct from this; true daily volume may need get_option_bars()
            # aggregation. Flagged, not silently assumed correct.
            volume=int(getattr(trade, "size", 0) or 0) if trade else 0,
            open_interest=open_interest,  # NOTE: up to 1-day lag per Alpaca's own docs
            implied_volatility=float(implied_vol) if implied_vol is not None else None,
            delta=getattr(greeks, "delta", None) if greeks else None,
            gamma=getattr(greeks, "gamma", None) if greeks else None,
            theta=getattr(greeks, "theta", None) if greeks else None,
            vega=getattr(greeks, "vega", None) if greeks else None,
            quote_timestamp=quote_timestamp,
        )

    def is_market_data_stale(self, symbol: str, max_age_seconds: int) -> bool:
        bars = self.get_price_bars(symbol, lookback_days=1)
        if not bars:
            return True
        age = (datetime.now(timezone.utc) - bars[-1].timestamp).total_seconds()
        return age > max_age_seconds

    # ── Execution ─────────────────────────────────────────────────────
    def submit_order(self, *, legs, quantity, client_order_id, limit_price) -> OrderResult:
        """Submit a paper-only single-leg or multi-leg option order."""
        if self.settings.alpaca_env.value != "paper":
            raise LiveTradingDisabledError("Live order submission is not implemented in this build.")

        submitted_at = datetime.now(timezone.utc)
        order_class = "SINGLE"
        try:
            from alpaca.trading.enums import OrderClass
            from alpaca.trading.enums import OrderSide as AlpacaOrderSide
            from alpaca.trading.enums import TimeInForce
            from alpaca.trading.requests import LimitOrderRequest, MarketOrderRequest, OptionLegRequest

            if not legs:
                raise ValueError("an option order requires at least one leg")

            def leg_value(leg, key, default=None):
                if isinstance(leg, dict):
                    return leg.get(key, default)
                if key == "symbol":
                    contract = getattr(leg, "contract", None)
                    return getattr(contract, "symbol", getattr(leg, "symbol", default))
                return getattr(leg, key, default)

            def alpaca_side(leg):
                side = str(getattr(leg_value(leg, "side"), "value", leg_value(leg, "side"))).upper()
                if side == "BUY":
                    return AlpacaOrderSide.BUY
                if side == "SELL":
                    return AlpacaOrderSide.SELL
                raise ValueError(f"unsupported option leg side: {side}")

            if len(legs) == 1:
                leg = legs[0]
                leg_quantity = int(leg_value(leg, "quantity", 1))
                request = MarketOrderRequest(
                    symbol=leg_value(leg, "symbol"),
                    qty=int(quantity) * leg_quantity,
                    side=alpaca_side(leg),
                    time_in_force=TimeInForce.DAY,
                    client_order_id=client_order_id,
                )
            else:
                if not 2 <= len(legs) <= 4:
                    raise ValueError("Alpaca multi-leg option orders require two to four legs")
                order_class = "MLEG"
                order_legs = [
                    OptionLegRequest(
                        symbol=leg_value(leg, "symbol"),
                        side=alpaca_side(leg),
                        ratio_qty=int(leg_value(leg, "quantity", 1)),
                    )
                    for leg in legs
                ]
                request_kwargs = {
                    "qty": int(quantity),
                    "order_class": OrderClass.MLEG,
                    "time_in_force": TimeInForce.DAY,
                    "legs": order_legs,
                    "client_order_id": client_order_id,
                }
                request = (
                    LimitOrderRequest(limit_price=limit_price, **request_kwargs)
                    if limit_price is not None
                    else MarketOrderRequest(**request_kwargs)
                )

            result = self._trading.submit_order(request)
            filled_qty_raw = getattr(result, "filled_qty", None)
            return OrderResult(
                order_id=str(result.id),
                client_order_id=str(result.client_order_id),
                status=str(result.status),
                filled_qty=int(float(filled_qty_raw)) if filled_qty_raw else 0,
                submitted_at=getattr(result, "submitted_at", None) or submitted_at,
                raw={"order_class": order_class, "legs": len(legs)},
            )
        except Exception as exc:  # noqa: BLE001 - preserve the pipeline journal on broker failures
            logger.warning("paper order submission failed for %s: %s", client_order_id, exc)
            return OrderResult(
                order_id="",
                client_order_id=client_order_id,
                status="rejected",
                filled_qty=0,
                submitted_at=submitted_at,
                raw={"order_class": order_class, "legs": len(legs), "error": str(exc)},
            )

    def health_check(self) -> dict[str, str]:
        status: dict[str, str] = {}
        try:
            acct = self._trading.get_account()
            status["ALPACA_CONNECTION"] = "OK"
            status["ACCOUNT"] = "OK" if acct.status == "ACTIVE" else f"WARN: status={acct.status}"
        except Exception as exc:  # noqa: BLE001 - health check must never raise
            status["ALPACA_CONNECTION"] = f"FAIL: {exc}"
            status["ACCOUNT"] = "FAIL: could not fetch account"

        try:
            bars = self.get_price_bars("SPY", lookback_days=5)
            status["MARKET_DATA"] = "OK" if bars else "FAIL: no bars returned"
        except Exception as exc:  # noqa: BLE001
            status["MARKET_DATA"] = f"FAIL: {exc}"

        try:
            chain = self.get_option_chain("SPY", min_dte=14, max_dte=45)
            status["OPTIONS_DATA"] = f"OK ({len(chain.contracts)} contracts)" if chain.contracts else "WARN: 0 contracts returned"
        except Exception as exc:  # noqa: BLE001
            status["OPTIONS_DATA"] = f"FAIL: {exc}"

        status["ENVIRONMENT"] = self.settings.alpaca_env.value.upper()
        return status
