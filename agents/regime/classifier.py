"""
Regime Analyst (Agent 2).

Classifies BULLISH / BEARISH / RANGE / HIGH_VOLATILITY / LOW_VOLATILITY /
UNCERTAIN from price history using deterministic technical features —
SMA/EMA trend, RSI, ATR, realized volatility, momentum, volume.

Design rule from the spec: "Do not rely only on an LLM. Use
deterministic/quantitative signals." The LLM layer (if used at all here)
only narrates *why* a regime was assigned — it never computes the label.

These features are inputs to a decision, not predictions of future
returns. Callers should not treat `confidence` as a probability of
profit.
"""
from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pandas as pd

from core.models.market import MarketRegime, PriceBar, RegimeLabel


def _sma(closes: pd.Series, window: int) -> float:
    if len(closes) < window:
        return float("nan")
    return float(closes.rolling(window).mean().iloc[-1])


def _ema(closes: pd.Series, span: int) -> float:
    if len(closes) < span:
        return float("nan")
    return float(closes.ewm(span=span, adjust=False).mean().iloc[-1])


def _rsi(closes: pd.Series, window: int = 14) -> float:
    if len(closes) < window + 1:
        return float("nan")
    delta = closes.diff().dropna()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(window).mean().iloc[-1]
    avg_loss = loss.rolling(window).mean().iloc[-1]
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return float(100 - (100 / (1 + rs)))


def _atr(df: pd.DataFrame, window: int = 14) -> float:
    if len(df) < window + 1:
        return float("nan")
    high_low = df["high"] - df["low"]
    high_close = (df["high"] - df["close"].shift()).abs()
    low_close = (df["low"] - df["close"].shift()).abs()
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    return float(tr.rolling(window).mean().iloc[-1])


def _realized_vol(closes: pd.Series, window: int = 20, annualize: bool = True) -> float:
    if len(closes) < window + 1:
        return float("nan")
    log_ret = np.log(closes / closes.shift(1)).dropna()
    vol = log_ret.rolling(window).std().iloc[-1]
    if annualize:
        vol *= np.sqrt(252)
    return float(vol)


def _momentum(closes: pd.Series, window: int = 10) -> float:
    if len(closes) < window + 1:
        return float("nan")
    return float(closes.iloc[-1] / closes.iloc[-window - 1] - 1.0)


class RegimeClassifier:
    """
    Thresholds are intentionally explicit constants here (not `Settings`)
    because they are model hyperparameters, not risk/business limits —
    but they are grouped in one place so they're easy to tune or move
    into Settings later without touching the classification logic.
    """

    TREND_WINDOW_FAST = 20
    TREND_WINDOW_SLOW = 50
    RSI_WINDOW = 14
    ATR_WINDOW = 14
    VOL_WINDOW = 20
    MOMENTUM_WINDOW = 10

    RSI_OVERBOUGHT = 65.0
    RSI_OVERSOLD = 35.0
    HIGH_VOL_ANNUALIZED = 0.35   # 35% annualized realized vol
    LOW_VOL_ANNUALIZED = 0.12    # 12% annualized realized vol
    RANGE_ATR_TO_PRICE = 0.012   # ATR under 1.2% of price with flat trend => range

    def classify(self, symbol: str, bars: list[PriceBar]) -> MarketRegime:
        if len(bars) < self.TREND_WINDOW_SLOW + 1:
            return MarketRegime(
                symbol=symbol,
                regime=RegimeLabel.UNCERTAIN,
                confidence=0.0,
                features={"reason_insufficient_bars": float(len(bars))},
                as_of=datetime.now(timezone.utc),
            )

        df = pd.DataFrame(
            {
                "open": [b.open for b in bars],
                "high": [b.high for b in bars],
                "low": [b.low for b in bars],
                "close": [b.close for b in bars],
                "volume": [b.volume for b in bars],
            }
        )
        closes = df["close"]
        price = float(closes.iloc[-1])

        sma_fast = _sma(closes, self.TREND_WINDOW_FAST)
        sma_slow = _sma(closes, self.TREND_WINDOW_SLOW)
        ema_fast = _ema(closes, self.TREND_WINDOW_FAST)
        rsi = _rsi(closes, self.RSI_WINDOW)
        atr = _atr(df, self.ATR_WINDOW)
        realized_vol = _realized_vol(closes, self.VOL_WINDOW)
        momentum = _momentum(closes, self.MOMENTUM_WINDOW)

        atr_pct = atr / price if price else float("nan")
        trend_spread_pct = (sma_fast - sma_slow) / sma_slow if sma_slow else float("nan")

        features = {
            "price": price,
            "sma_fast": sma_fast,
            "sma_slow": sma_slow,
            "ema_fast": ema_fast,
            "rsi": rsi,
            "atr": atr,
            "atr_pct_of_price": atr_pct,
            "realized_vol_annualized": realized_vol,
            "momentum_10d": momentum,
            "trend_spread_pct": trend_spread_pct,
        }

        regime, confidence = self._decide(
            price=price,
            sma_fast=sma_fast,
            sma_slow=sma_slow,
            rsi=rsi,
            atr_pct=atr_pct,
            realized_vol=realized_vol,
            momentum=momentum,
            trend_spread_pct=trend_spread_pct,
        )

        return MarketRegime(
            symbol=symbol,
            regime=regime,
            confidence=confidence,
            features=features,
            as_of=datetime.now(timezone.utc),
        )

    def _decide(
        self,
        *,
        price: float,
        sma_fast: float,
        sma_slow: float,
        rsi: float,
        atr_pct: float,
        realized_vol: float,
        momentum: float,
        trend_spread_pct: float,
    ) -> tuple[RegimeLabel, float]:
        if any(np.isnan(x) for x in (sma_fast, sma_slow, rsi, atr_pct, realized_vol, momentum)):
            return RegimeLabel.UNCERTAIN, 0.0

        # Volatility regime takes precedence — it changes which strategies are even eligible.
        if realized_vol >= self.HIGH_VOL_ANNUALIZED:
            confidence = min(1.0, 0.5 + (realized_vol - self.HIGH_VOL_ANNUALIZED))
            return RegimeLabel.HIGH_VOLATILITY, round(confidence, 4)

        # Range-bound: flat trend + tight ATR
        if abs(trend_spread_pct) < 0.01 and atr_pct < self.RANGE_ATR_TO_PRICE:
            confidence = min(1.0, 0.55 + (self.RANGE_ATR_TO_PRICE - atr_pct) * 10)
            return RegimeLabel.RANGE, round(confidence, 4)

        if realized_vol <= self.LOW_VOL_ANNUALIZED and abs(trend_spread_pct) < 0.02:
            confidence = min(1.0, 0.5 + (self.LOW_VOL_ANNUALIZED - realized_vol))
            return RegimeLabel.LOW_VOLATILITY, round(confidence, 4)

        # Directional
        bullish_votes = sum(
            [
                price > sma_fast > sma_slow,
                rsi > 50,
                momentum > 0,
                trend_spread_pct > 0,
            ]
        )
        bearish_votes = sum(
            [
                price < sma_fast < sma_slow,
                rsi < 50,
                momentum < 0,
                trend_spread_pct < 0,
            ]
        )

        if bullish_votes >= 3:
            confidence = 0.5 + 0.125 * bullish_votes
            if rsi >= self.RSI_OVERBOUGHT:
                confidence -= 0.05  # overbought tempers conviction slightly
            return RegimeLabel.BULLISH, round(min(confidence, 0.97), 4)

        if bearish_votes >= 3:
            confidence = 0.5 + 0.125 * bearish_votes
            if rsi <= self.RSI_OVERSOLD:
                confidence -= 0.05
            return RegimeLabel.BEARISH, round(min(confidence, 0.97), 4)

        return RegimeLabel.UNCERTAIN, round(0.3 + 0.05 * max(bullish_votes, bearish_votes), 4)
