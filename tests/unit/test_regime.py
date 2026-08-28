from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from agents.regime.classifier import RegimeClassifier
from core.models.market import PriceBar, RegimeLabel


def _bars_from_closes(closes: list[float]) -> list[PriceBar]:
    now = datetime.now(timezone.utc)
    bars = []
    for i, c in enumerate(closes):
        bars.append(
            PriceBar(
                timestamp=now - timedelta(days=len(closes) - i),
                open=c * 0.999, high=c * 1.005, low=c * 0.995, close=c, volume=1_000_000,
            )
        )
    return bars


def test_uptrend_classified_bullish():
    closes = list(100 + np.linspace(0, 30, 90) + np.random.default_rng(1).normal(0, 0.3, 90))
    regime = RegimeClassifier().classify("TEST", _bars_from_closes(closes))
    assert regime.regime == RegimeLabel.BULLISH
    assert regime.confidence > 0.5


def test_downtrend_classified_bearish():
    closes = list(130 - np.linspace(0, 30, 90) + np.random.default_rng(2).normal(0, 0.3, 90))
    regime = RegimeClassifier().classify("TEST", _bars_from_closes(closes))
    assert regime.regime == RegimeLabel.BEARISH
    assert regime.confidence > 0.5


def test_flat_low_vol_series_not_classified_bullish_or_bearish():
    rng = np.random.default_rng(3)
    closes = list(100 + rng.normal(0, 0.05, 90))
    regime = RegimeClassifier().classify("TEST", _bars_from_closes(closes))
    assert regime.regime in (RegimeLabel.RANGE, RegimeLabel.LOW_VOLATILITY, RegimeLabel.UNCERTAIN)


def test_insufficient_history_is_uncertain():
    closes = [100.0] * 10  # far fewer than TREND_WINDOW_SLOW + 1
    regime = RegimeClassifier().classify("TEST", _bars_from_closes(closes))
    assert regime.regime == RegimeLabel.UNCERTAIN
    assert regime.confidence == 0.0


def test_regime_features_are_json_serializable_via_to_dict():
    closes = list(100 + np.linspace(0, 20, 90))
    regime = RegimeClassifier().classify("TEST", _bars_from_closes(closes))
    d = regime.to_dict()
    assert d["symbol"] == "TEST"
    assert isinstance(d["features"], dict)
    assert isinstance(d["confidence"], float)
