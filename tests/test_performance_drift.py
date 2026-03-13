import pytest
import pandas as pd
import numpy as np
from analysis.performance_drift import PerformanceDriftDetector

def generate_mock_trades(n_good, n_bad):
    # Create an artificial sequence with realistic variance (to prevent Inf/NaN profit factors)
    good_pnl = np.random.normal(2, 5, n_good) 
    bad_pnl = np.random.normal(-5, 2, n_bad)
    
    pnl = np.concatenate([good_pnl, bad_pnl])
    return pd.DataFrame({'net_pnl': pnl})

def test_insufficient_data():
    df = pd.DataFrame({'net_pnl': [1, 2, 3]})
    res = PerformanceDriftDetector.calculate_drift(df, min_trades=10)
    assert res['classification'] == "INSUFFICIENT_DATA"

def test_drift_normal():
    np.random.seed(42)
    # 500 stationary trades 
    df = pd.DataFrame({'net_pnl': np.random.normal(5, 5, 500)})
    
    res = PerformanceDriftDetector.calculate_drift(
        df, 
        recent_window=50, 
        historical_baseline_window=200, 
        min_trades=100, 
        use_percentiles=True
    )
    
    # Consistent stationary distribution should hover around 0 Z-score -> NORMAL
    assert res['classification'] == "NORMAL"
    assert res['drift_score_z'] > -1.5

def test_drift_critical_decay():
    np.random.seed(42)
    # 400 great trades, 100 terrible trades (recent window is bleeding)
    df = generate_mock_trades(400, 100)
    
    res = PerformanceDriftDetector.calculate_drift(
        df, 
        recent_window=50, 
        historical_baseline_window=None, 
        min_trades=100, 
        use_percentiles=True
    )
    
    # The recent 50 trades will have atrocious Win Rates and Negative Sharpe compared to the glorious past
    assert res['classification'] in ["WARNING", "CRITICAL"]
    assert res['drift_score_z'] < -1.0
    
    # Breakdown should show terrible z-scores internally
    assert res['metric_zscores']['rolling_sharpe_zscore'] < 0
    assert res['metric_zscores']['rolling_win_rate_zscore'] < 0
