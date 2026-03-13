import pytest
import pandas as pd
import numpy as np
from regime.volatility_detector import VolatilityRegimeDetector

def generate_mock_data(volatility_type: str, periods: int = 50) -> pd.DataFrame:
    """Generates synthetic price data with different volatility profiles."""
    np.random.seed(42)  # For reproducible tests
    
    base_price = 100.0
    index = pd.date_range(start='2026-01-01', periods=periods, freq='4h')
    
    if volatility_type == "LOW":
        # Small random walk
        changes = np.random.normal(0, 0.005, periods) # 0.5% std dev
    elif volatility_type == "MEDIUM":
        changes = np.random.normal(0, 0.02, periods)  # 2.0% std dev
    else: # HIGH
        changes = np.random.normal(0, 0.05, periods)  # 5.0% std dev
        
    closes = base_price * (1 + changes).cumprod()
    
    # Generate somewhat realistic high/lows based on close
    highs = closes * (1 + abs(np.random.normal(0, 0.002, periods)))
    lows = closes * (1 - abs(np.random.normal(0, 0.002, periods)))
    
    df = pd.DataFrame({
        'close': closes,
        'high': highs,
        'low': lows
    }, index=index)
    
    return df

def test_atr_calculation():
    detector = VolatilityRegimeDetector(atr_period=14)
    df = generate_mock_data("MEDIUM", 30)
    
    atr = detector.calculate_atr(df)
    
    # First 13 values should be NaN
    assert pd.isna(atr.iloc[0])
    assert pd.isna(atr.iloc[12])
    
    # 14th value should be valid
    assert not pd.isna(atr.iloc[13])
    assert atr.iloc[-1] > 0

def test_volatility_percent_calculation():
    detector = VolatilityRegimeDetector(atr_period=14)
    df = generate_mock_data("HIGH", 30)
    
    vol_pct = detector.calculate_volatility_percent(df)
    
    # First 14 values should be NaN (1 for pct_change + 13 for rolling std)
    assert pd.isna(vol_pct.iloc[13])
    
    # 15th value should be valid
    assert not pd.isna(vol_pct.iloc[14])
    assert vol_pct.iloc[-1] > 0

def test_detect_low_volatility():
    # Adjust thresholds to match synthetic data generation
    detector = VolatilityRegimeDetector(atr_period=14, low_threshold=1.0, high_threshold=3.5)
    df = generate_mock_data("LOW", 50)
    
    regime = detector.detect_regime(df)
    assert regime == "LOW"

def test_detect_medium_volatility():
    detector = VolatilityRegimeDetector(atr_period=14, low_threshold=1.0, high_threshold=3.5)
    df = generate_mock_data("MEDIUM", 50)
    
    regime = detector.detect_regime(df)
    assert regime == "MEDIUM"

def test_detect_high_volatility():
    detector = VolatilityRegimeDetector(atr_period=14, low_threshold=1.0, high_threshold=3.5)
    df = generate_mock_data("HIGH", 50)
    
    regime = detector.detect_regime(df)
    assert regime == "HIGH"

def test_insufficient_data():
    detector = VolatilityRegimeDetector(atr_period=14)
    df = generate_mock_data("MEDIUM", 10) # Less than period
    
    # Should safely return default MEDIUM without crashing
    regime = detector.detect_regime(df)
    assert regime == "MEDIUM"
