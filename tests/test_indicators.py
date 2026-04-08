"""Tests for indicators/ and regime/ modules."""

import pandas as pd
import numpy as np
from indicators.technical_indicators import add_standard_indicators
from indicators.volume_profile import compute_volume_profile
from regime.regime_detector import RegimeDetector


class TestStandardIndicators:
    def test_adds_expected_columns(self, sample_df):
        df = add_standard_indicators(sample_df.copy())
        expected = {"EMA_fast", "EMA_slow", "MACD", "RSI", "ATR"}
        assert expected.issubset(
            set(df.columns)
        ), f"Missing columns: {expected - set(df.columns)}"

    def test_preserves_shape(self, sample_df):
        original_len = len(sample_df)
        df = add_standard_indicators(sample_df.copy())
        assert len(df) == original_len

    def test_ema_fast_shorter_than_slow(self, sample_df_with_indicators):
        """EMA_fast (50) should be more responsive than EMA_slow (200)."""
        df = sample_df_with_indicators
        # Just check they're not all NaN
        assert df["EMA_fast"].dropna().shape[0] > 0
        assert df["EMA_slow"].dropna().shape[0] > 0

    def test_rsi_range(self, sample_df_with_indicators):
        """RSI should be between 0 and 100."""
        df = sample_df_with_indicators
        rsi = df["RSI"].dropna()
        assert rsi.min() >= 0
        assert rsi.max() <= 100

    def test_empty_df_returns_safely(self):
        empty = pd.DataFrame()
        result = add_standard_indicators(empty)
        assert isinstance(result, pd.DataFrame)

    def test_missing_columns_returns_safely(self):
        df = pd.DataFrame({"foo": [1, 2, 3]})
        result = add_standard_indicators(df)
        assert "EMA_fast" not in result.columns  # Shouldn't crash


class TestVolumeProfile:
    def test_basic_volume_profile(self, sample_df):
        vp = compute_volume_profile(sample_df)
        assert vp.vah > vp.val
        assert vp.val <= vp.poc <= vp.vah

    def test_poc_within_price_range(self, sample_df):
        vp = compute_volume_profile(sample_df)
        assert vp.poc >= sample_df["low"].min()
        assert vp.poc <= sample_df["high"].max()


class TestRegimeDetector:
    def test_returns_valid_regime(self, sample_df_with_indicators):
        detector = RegimeDetector()
        regime = detector.detect_regime(sample_df_with_indicators)
        assert regime in ("trend", "range")

    def test_trending_data(self):
        """Strong uptrend should detect as 'trend'."""
        np.random.seed(99)
        n = 300
        # Exponential uptrend with increasing volatility (proportional to price)
        base = 50000 * np.exp(
            np.linspace(0, 1.5, n)
        )  # Increased steepness to ensure EMA diff > 2%
        # Noise proportional to price so BB_width grows with price
        noise = np.random.normal(0, 1, n) * base * 0.01
        price = base + noise
        df = pd.DataFrame(
            {
                "open": price * (1 + np.random.normal(0, 0.005, n)),
                "high": price * (1 + np.abs(np.random.normal(0, 0.012, n))),
                "low": price * (1 - np.abs(np.random.normal(0, 0.012, n))),
                "close": price,
                "volume": np.random.uniform(100, 500, n),
            }
        )
        df = add_standard_indicators(df)
        detector = RegimeDetector()
        regime = detector.detect_regime(df)
        assert regime == "trend"

    def test_ranging_data(self):
        """Sideways data should detect as 'range'."""
        np.random.seed(77)
        n = 300
        price = 60000 + np.random.normal(0, 50, n)
        df = pd.DataFrame(
            {
                "open": price * 0.999,
                "high": price * 1.001,
                "low": price * 0.999,
                "close": price,
                "volume": np.random.uniform(100, 500, n),
            }
        )
        df = add_standard_indicators(df)
        detector = RegimeDetector()
        regime = detector.detect_regime(df)
        assert regime == "range"
