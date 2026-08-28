"""
MockBrokerAdapter — synthetic but internally consistent market/account
data, seeded per-symbol so results are reproducible run-to-run.

This is what DRY_RUN uses by default and what unit/simulation tests run
against. It implements the exact same BrokerAdapter surface as the real
Alpaca adapter, so `core/orchestration/pipeline.py` never needs to know
which one it's talking to.
"""
from __future__ import annotations

import hashlib
from datetime import date, datetime, timedelta, timezone

import numpy as np

from core.config.settings import Settings
from core.interfaces.broker import AccountSnapshot, BrokerPosition, OrderResult
from core.models.market import PriceBar
from core.models.options import OptionChainSlice, OptionContract, OptionRight


def _seed_for(symbol: str) -> int:
    return int(hashlib.sha256(symbol.encode()).hexdigest(), 16) % (2**31)


class MockBrokerAdapter:
    def __init__(self, settings: Settings, starting_equity: float = 100_000.0):
        self.settings = settings
        self._equity = starting_equity
        self._peak_equity = starting_equity
        self._daily_pnl = 0.0
        self._recent_order_ids: list[str] = []

    def get_account(self) -> AccountSnapshot:
        return AccountSnapshot(
            equity=self._equity,
            buying_power=self._equity * 2,  # simplified Reg-T style buying power for paper simulation
            cash=self._equity,
            daily_pnl=self._daily_pnl,
            peak_equity=self._peak_equity,
            is_paper=True,
        )

    def get_positions(self) -> list[BrokerPosition]:
        return []

    def get_price_bars(self, symbol: str, lookback_days: int) -> list[PriceBar]:
        rng = np.random.default_rng(_seed_for(symbol))
        base_price = 50 + (_seed_for(symbol) % 400)
        drift = rng.normal(0.0003, 0.0002)
        vol = rng.uniform(0.010, 0.028)

        n = lookback_days + 60  # extra history so SMA(50)/EMA(20) have enough lookback
        log_returns = rng.normal(drift, vol, size=n)
        closes = base_price * np.exp(np.cumsum(log_returns))

        bars: list[PriceBar] = []
        today = datetime.now(timezone.utc)
        for i, close in enumerate(closes):
            ts = today - timedelta(days=(n - i))
            intraday_range = close * rng.uniform(0.003, 0.015)
            high = close + intraday_range * rng.uniform(0.3, 1.0)
            low = close - intraday_range * rng.uniform(0.3, 1.0)
            open_ = float(np.clip(rng.normal(close, intraday_range * 0.3), low, high))
            volume = float(rng.uniform(1_000_000, 20_000_000))
            bars.append(
                PriceBar(
                    timestamp=ts, open=round(open_, 2), high=round(float(high), 2),
                    low=round(float(low), 2), close=round(float(close), 2), volume=volume,
                )
            )
        return bars[-lookback_days:] if lookback_days < len(bars) else bars

    def get_option_chain(self, symbol: str, min_dte: int, max_dte: int) -> OptionChainSlice:
        rng = np.random.default_rng(_seed_for(symbol) + 1)
        bars = self.get_price_bars(symbol, lookback_days=60)
        spot = bars[-1].close
        realized_vol = float(np.std(np.diff(np.log([b.close for b in bars])))) * np.sqrt(252)
        realized_vol = max(realized_vol, 0.10)

        today = date.today()
        expirations = [today + timedelta(days=d) for d in (min_dte + 3, (min_dte + max_dte) // 2, max_dte - 3)]

        contracts: list[OptionContract] = []
        strikes = [round(spot * m, 1) for m in np.arange(0.80, 1.21, 0.025)]

        for exp in expirations:
            dte = max((exp - today).days, 1)
            t = dte / 365
            for strike in strikes:
                for right in (OptionRight.CALL, OptionRight.PUT):
                    moneyness = strike / spot
                    # Cheap, deterministic pseudo-Black-Scholes-ish pricing — good enough
                    # for exercising the pipeline; NOT a real pricing model.
                    intrinsic = max(spot - strike, 0) if right == OptionRight.CALL else max(strike - spot, 0)
                    time_value = spot * realized_vol * np.sqrt(t) * np.exp(-2 * (moneyness - 1) ** 2) * 0.4
                    fair = max(intrinsic + time_value, 0.02)
                    half_spread = max(fair * rng.uniform(0.02, 0.08), 0.01)
                    bid = round(max(fair - half_spread, 0.01), 2)
                    ask = round(fair + half_spread, 2)
                    volume = int(rng.integers(0, 500) * np.exp(-3 * abs(moneyness - 1)))
                    oi = int(rng.integers(0, 5000) * np.exp(-2 * abs(moneyness - 1)))
                    delta = float(np.clip(
                        (1 if right == OptionRight.CALL else -1) * (1 - abs(moneyness - 1) * 2), -0.99, 0.99
                    ))
                    contracts.append(
                        OptionContract(
                            symbol=f"{symbol}{exp.strftime('%y%m%d')}{'C' if right == OptionRight.CALL else 'P'}{int(strike*1000):08d}",
                            underlying=symbol,
                            expiration=exp,
                            strike=strike,
                            right=right,
                            bid=bid,
                            ask=ask,
                            last=round((bid + ask) / 2, 2),
                            volume=volume,
                            open_interest=oi,
                            implied_volatility=round(realized_vol * rng.uniform(0.9, 1.15), 4),
                            delta=round(delta, 3),
                            gamma=None, theta=None, vega=None,
                        )
                    )

        return OptionChainSlice(
            underlying=symbol,
            fetched_at=datetime.now(timezone.utc).isoformat(),
            contracts=tuple(contracts),
        )

    def is_market_data_stale(self, symbol: str, max_age_seconds: int) -> bool:
        return False  # mock data is always "fresh" by construction

    def submit_order(self, *, legs, quantity, client_order_id, limit_price) -> OrderResult:
        self._recent_order_ids.append(client_order_id)
        return OrderResult(
            order_id=f"mock_{client_order_id}",
            client_order_id=client_order_id,
            status="filled",
            filled_qty=quantity,
            submitted_at=datetime.now(timezone.utc),
            raw={"mode": "MOCK", "legs": len(legs)},
        )

    def health_check(self) -> dict[str, str]:
        return {
            "ALPACA_CONNECTION": "MOCK (no network call made)",
            "ENVIRONMENT": "PAPER (mock adapter)",
            "ACCOUNT": "OK (synthetic)",
            "MARKET_DATA": "OK (synthetic, seeded)",
            "OPTIONS_DATA": "OK (synthetic, seeded)",
        }
