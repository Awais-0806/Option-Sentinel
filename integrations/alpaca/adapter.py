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
from datetime import datetime, timedelta, timezone

from core.config.settings import Settings
from core.interfaces.broker import AccountSnapshot, BrokerPosition, OrderResult
from core.models.market import PriceBar
from core.models.options import OptionChainSlice, OptionContract, OptionRight

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

        if settings.alpaca_env.value == "live" and not settings.is_live_trading_permitted:
            raise LiveTradingDisabledError(
                "ALPACA_ENV=live but ALPACA_LIVE_TRADING_CONFIRMED is not set. "
                "This build does not implement live execution. Refusing to start."
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

        paper = settings.alpaca_env.value == "paper"
        self._trading = TradingClient(
            api_key=settings.alpaca_api_key,
            secret_key=settings.alpaca_secret_key,
            paper=paper,
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

    def get_option_chain(self, symbol: str, min_dte: int, max_dte: int) -> OptionChainSlice:
        # NOTE: alpaca-py's options-chain surface is evolving quickly; this
        # method intentionally isolates that volatility to one place.
        # Implementation wired up once paper credentials are available —
        # see docs/ARCHITECTURE.md "Known limitations" for current status.
        raise NotImplementedError(
            "Live option chain retrieval needs valid ALPACA_API_KEY/SECRET to implement "
            "and verify against real response shapes. Use the mock adapter until then."
        )

    def is_market_data_stale(self, symbol: str, max_age_seconds: int) -> bool:
        bars = self.get_price_bars(symbol, lookback_days=1)
        if not bars:
            return True
        age = (datetime.now(timezone.utc) - bars[-1].timestamp).total_seconds()
        return age > max_age_seconds

    # ── Execution ─────────────────────────────────────────────────────
    def submit_order(self, *, legs, quantity, client_order_id, limit_price) -> OrderResult:
        if self.settings.alpaca_env.value == "live":
            raise LiveTradingDisabledError("Live order submission is not implemented in this build.")
        raise NotImplementedError(
            "Multi-leg options order submission is implemented once paper credentials "
            "are verified end-to-end (Milestone 8/10). Use EXECUTION_MODE=DRY_RUN or "
            "SIMULATION until then."
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

        status["OPTIONS_DATA"] = "NOT_IMPLEMENTED: see integrations/alpaca/adapter.py"
        status["ENVIRONMENT"] = self.settings.alpaca_env.value.upper()
        return status
