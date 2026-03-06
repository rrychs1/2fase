
import pandas as pd
import numpy as np
import pytest
from indicators.technical_indicators import add_standard_indicators

def create_synthetic_trend(length=100, slope=1.0):
    """Creates a DataFrame with a clear linear trend."""
    prices = np.linspace(100, 100 + (length * slope), length)
    df = pd.DataFrame({
        'timestamp': pd.date_range(start='2024-01-01', periods=length, freq='4h'),
        'open': prices,
        'high': prices + 1,
        'low': prices - 1,
        'close': prices,
        'volume': 1000
    })
    return df

def create_synthetic_range(length=100, center=100, amplitude=5):
    """Creates a DataFrame with a oscillating range."""
    x = np.linspace(0, 10 * np.pi, length)
    prices = center + amplitude * np.sin(x)
    df = pd.DataFrame({
        'timestamp': pd.date_range(start='2024-01-01', periods=length, freq='4h'),
        'open': prices,
        'high': prices + 1,
        'low': prices - 1,
        'close': prices,
        'volume': 1000
    })
    return df

def test_ema_alignment():
    """Verify that EMA follows the trend correctly."""
    df = create_synthetic_trend(length=300, slope=1.0)
    df = add_standard_indicators(df)
    
    # In a clear uptrend, close > EMA_fast > EMA_slow
    last = df.iloc[-1]
    assert last['close'] > last['EMA_fast']
    assert last['EMA_fast'] > last['EMA_slow']

def test_bb_width_in_range():
    """Verify Bollinger Bands narrowing in a range."""
    df = create_synthetic_range(length=200, amplitude=2) # Narrow range
    df = add_standard_indicators(df)
    
    # BB Width should be relatively low and stable
    last_bbw = df['BB_width'].tail(20).mean()
    assert last_bbw < 5.0 

def test_adx_in_strong_trend():
    """Verify ADX is high in a strong trend."""
    df = create_synthetic_trend(length=100, slope=5.0) # Strong trend
    df = add_standard_indicators(df)
    
    # ADX should be > 25 (standard threshold for trend)
    assert df.iloc[-1]['ADX'] > 25

if __name__ == "__main__":
    pytest.main([__file__])
