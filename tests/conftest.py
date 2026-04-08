"""
Shared pytest fixtures for the trading bot test suite.
"""

import pytest
import numpy as np
import pandas as pd
from datetime import datetime, timedelta

from config.config_loader import Config
from common.types import Signal, SignalAction, Side, VolumeProfile
from indicators.technical_indicators import add_standard_indicators
from indicators.volume_profile import compute_volume_profile


@pytest.fixture
def config():
    """Config with deterministic values (no .env dependency)."""
    cfg = Config()
    cfg.LEVERAGE = 3
    cfg.MAX_RISK_PER_TRADE = 0.01
    cfg.DAILY_LOSS_LIMIT = 0.02
    cfg.GRID_LEVELS = 5
    cfg.DCA_STEPS = 3
    cfg.ANALYSIS_ONLY = True
    return cfg


@pytest.fixture
def sample_df():
    """
    300-row OHLCV DataFrame with realistic BTC-like price action.
    Includes a trend phase and a ranging phase.
    """
    np.random.seed(42)
    n = 300
    timestamps = [datetime(2025, 8, 1) + timedelta(hours=4 * i) for i in range(n)]

    # Simulate price: start at 60000, random walk
    returns = np.random.normal(0.0005, 0.015, n)
    close = 60000 * np.cumprod(1 + returns)
    high = close * (1 + np.abs(np.random.normal(0, 0.005, n)))
    low = close * (1 - np.abs(np.random.normal(0, 0.005, n)))
    open_ = close * (1 + np.random.normal(0, 0.002, n))
    volume = np.random.uniform(100, 1000, n)

    df = pd.DataFrame(
        {
            "timestamp": timestamps,
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
        }
    )
    return df


@pytest.fixture
def sample_df_with_indicators(sample_df):
    """Sample DF with all standard indicators computed."""
    return add_standard_indicators(sample_df.copy())


@pytest.fixture
def volume_profile(sample_df):
    """VolumeProfile from sample data."""
    return compute_volume_profile(sample_df)


@pytest.fixture
def signal_long():
    """Pre-built ENTER_LONG signal."""
    return Signal(
        symbol="BTC/USDT",
        action=SignalAction.ENTER_LONG,
        side=Side.LONG,
        price=60000.0,
        amount=0.01,
        stop_loss=58000.0,
        take_profit=64000.0,
        strategy="test",
        confidence=0.9,
    )


@pytest.fixture
def signal_short():
    """Pre-built ENTER_SHORT signal."""
    return Signal(
        symbol="BTC/USDT",
        action=SignalAction.ENTER_SHORT,
        side=Side.SHORT,
        price=60000.0,
        amount=0.01,
        stop_loss=62000.0,
        take_profit=56000.0,
        strategy="test",
        confidence=0.9,
    )
