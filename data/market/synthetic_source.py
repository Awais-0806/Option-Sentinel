"""
SYNTHETIC_OPTIONS_DATA generator (Phase D/E).

This module exists because Claude's sandbox has no network access to any
real historical-options data vendor, and no dataset was found in the
repository (Phase A). Everything this module produces is synthetic and
MUST be labeled DataProvenance.SYNTHETIC_OPTIONS_DATA everywhere it is
used, logged, or reported. It is never to be described as "historical
data," "real market data," or "backtest data" without that qualifier.

DISCLOSED ASSUMPTIONS (read before trusting any number derived from this):

  Underlying price path:
    - If `underlying_bars` is supplied (e.g. real Alpaca stock bars, which
      ARE real even when the options built on top of them are not), that
      real price path is used and only the OPTIONS built on top of it are
      synthetic.
    - Otherwise, a synthetic geometric Brownian motion path is generated
      with a fixed seed (see integrations/alpaca/mock_adapter.py, which
      this delegates to for consistency with the rest of the project).

  Option pricing model: Black-Scholes-Merton, European-style, no dividend
    yield adjustment, continuously-compounded flat risk-free rate.

  Volatility assumption: a single flat annualized IV per (day, symbol),
    derived from the trailing realized volatility of the underlying path
    (same calculation as agents/regime/classifier.py), NOT a real implied-
    volatility surface. No skew, no term structure, no smile.

  Strike selection: a fixed grid at 2.5% increments from 80% to 120% of
    spot, matching tests/unit/test_strategies.py's synthetic chain.

  Expiration selection: three fixed DTE buckets per day (~21, ~33, ~42
    days out), matching the MIN_DTE/MAX_DTE windows the strategies use.

  Bid/ask spread model: a fixed percentage of theoretical fair value
    (default 4%), NOT derived from any real order-book/liquidity data.

  Transaction costs / slippage: NOT baked into the quotes themselves —
    applied separately at trade-simulation time (see backtest/runner.py
    and the cost-sensitivity sweep), so they can be varied independently.

  Random seed: deterministic, derived from (underlying, as_of_date) via
    SHA-256, same pattern as the mock broker adapter, so two runs with
    identical inputs produce byte-identical output (Phase O).
"""
from __future__ import annotations

import hashlib
import math
from datetime import date, timedelta

import numpy as np

from backtest.data_schema import DataProvenance, HistoricalDataset, HistoricalDay
from core.models.market import PriceBar
from core.models.options import OptionContract, OptionRight

# ── Disclosed, centralized assumptions (Phase D requirement) ──────────
SPREAD_PCT_OF_FAIR_VALUE = 0.04
STRIKE_GRID_MONEYNESS = tuple(float(round(m, 3)) for m in np.arange(0.80, 1.21, 0.025))
DTE_BUCKETS = (21, 33, 42)
RISK_FREE_RATE = 0.045  # flat, matches typical short-term T-bill yield at time of writing; disclosed, not fitted
REALIZED_VOL_LOOKBACK_DAYS = 20


def _seed_for(underlying: str, as_of: date) -> int:
    key = f"{underlying}|{as_of.isoformat()}"
    return int(hashlib.sha256(key.encode()).hexdigest(), 16) % (2**31)


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _black_scholes(spot: float, strike: float, t_years: float, vol: float, right: OptionRight, r: float = RISK_FREE_RATE) -> float:
    if t_years <= 0 or vol <= 0 or spot <= 0 or strike <= 0:
        return max(spot - strike, 0.0) if right == OptionRight.CALL else max(strike - spot, 0.0)
    d1 = (math.log(spot / strike) + (r + 0.5 * vol * vol) * t_years) / (vol * math.sqrt(t_years))
    d2 = d1 - vol * math.sqrt(t_years)
    if right == OptionRight.CALL:
        return spot * _norm_cdf(d1) - strike * math.exp(-r * t_years) * _norm_cdf(d2)
    return strike * math.exp(-r * t_years) * _norm_cdf(-d2) - spot * _norm_cdf(-d1)


def _trailing_realized_vol(closes: list[float], lookback: int = REALIZED_VOL_LOOKBACK_DAYS) -> float:
    if len(closes) < lookback + 1:
        return 0.20  # disclosed fallback for the first `lookback` days of a series
    window = np.array(closes[-(lookback + 1):])
    log_ret = np.diff(np.log(window))
    return float(max(np.std(log_ret) * np.sqrt(252), 0.05))


def generate_synthetic_dataset(
    underlying: str,
    start: date,
    end: date,
    *,
    underlying_bars: list[PriceBar] | None = None,
    spread_pct: float = SPREAD_PCT_OF_FAIR_VALUE,
) -> HistoricalDataset:
    """
    Builds a full SYNTHETIC_OPTIONS_DATA dataset for `underlying` across
    every trading day from `start` to `end` inclusive (weekends skipped;
    no holiday calendar — a disclosed simplification).
    """
    if underlying_bars is not None:
        price_source = "real_underlying_path_supplied"
        dated_closes = [(b.timestamp.date(), b.close) for b in underlying_bars]
    else:
        price_source = "synthetic_gbm_path"
        dated_closes = _synthetic_underlying_path(underlying, start, end)

    closes_by_date = dict(dated_closes)
    all_dates = sorted(closes_by_date.keys())
    trading_dates = [d for d in all_dates if start <= d <= end and d.weekday() < 5]

    days: list[HistoricalDay] = []
    for i, as_of in enumerate(trading_dates):
        trailing_closes = [closes_by_date[d] for d in trading_dates[: i + 1]]
        spot = trailing_closes[-1]
        vol = _trailing_realized_vol(trailing_closes)
        rng = np.random.default_rng(_seed_for(underlying, as_of))

        contracts: list[OptionContract] = []
        for dte in DTE_BUCKETS:
            expiration = as_of + timedelta(days=dte)
            t_years = dte / 365.0
            for moneyness in STRIKE_GRID_MONEYNESS:
                strike = round(spot * moneyness, 1)
                for right in (OptionRight.CALL, OptionRight.PUT):
                    fair = max(_black_scholes(spot, strike, t_years, vol, right), 0.01)
                    half_spread = max(fair * spread_pct / 2, 0.01)
                    bid = round(max(fair - half_spread, 0.01), 2)
                    ask = round(fair + half_spread, 2)
                    volume = int(rng.integers(0, 400) * math.exp(-3 * abs(moneyness - 1)))
                    oi = int(rng.integers(0, 4000) * math.exp(-2 * abs(moneyness - 1)))
                    contracts.append(
                        OptionContract(
                            symbol=f"{underlying}{expiration.strftime('%y%m%d')}"
                            f"{'C' if right == OptionRight.CALL else 'P'}{int(strike*1000):08d}",
                            underlying=underlying, expiration=expiration, strike=strike, right=right,
                            bid=bid, ask=ask, last=round((bid + ask) / 2, 2),
                            volume=volume, open_interest=oi, implied_volatility=round(vol, 4),
                        )
                    )
        days.append(HistoricalDay(as_of_date=as_of, underlying=underlying, underlying_close=spot, contracts=tuple(contracts)))

    metadata = {
        "pricing_model": "black_scholes_merton",
        "risk_free_rate": RISK_FREE_RATE,
        "volatility_assumption": f"trailing_{REALIZED_VOL_LOOKBACK_DAYS}d_realized_vol_flat_no_smile",
        "strike_grid_moneyness": list(STRIKE_GRID_MONEYNESS),
        "expiration_grid_dte": list(DTE_BUCKETS),
        "spread_model": f"{spread_pct:.1%}_of_fair_value",
        "transaction_cost_model": "applied_separately_at_trade_time_see_backtest.costs",
        "slippage_model": "applied_separately_at_trade_time_see_backtest.costs",
        "underlying_price_source": price_source,
        "date_range": [start.isoformat(), end.isoformat()],
    }
    return HistoricalDataset(underlying=underlying, provenance=DataProvenance.SYNTHETIC_OPTIONS_DATA, days=tuple(days), metadata=metadata)


def _synthetic_underlying_path(underlying: str, start: date, end: date) -> list[tuple[date, float]]:
    """Deterministic GBM path, seeded off (underlying, start) — same
    approach as integrations/alpaca/mock_adapter.py, kept independent here
    so the backtest data layer has zero runtime dependency on the broker
    adapter module."""
    rng = np.random.default_rng(_seed_for(underlying, start))
    base_price = 50 + (_seed_for(underlying, start) % 400)
    drift = rng.normal(0.0003, 0.0002)
    vol = rng.uniform(0.010, 0.028)

    n_days = (end - start).days + REALIZED_VOL_LOOKBACK_DAYS + 5  # buffer so early days have trailing history
    lookback_start = start - timedelta(days=REALIZED_VOL_LOOKBACK_DAYS + 5)
    log_returns = rng.normal(drift, vol, size=n_days)
    closes = base_price * np.exp(np.cumsum(log_returns))

    out = []
    for i in range(n_days):
        d = lookback_start + timedelta(days=i)
        out.append((d, round(float(closes[i]), 2)))
    return out
