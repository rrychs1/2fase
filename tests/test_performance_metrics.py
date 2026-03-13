import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from analysis.performance_metrics import PerformanceMetrics

def test_equity_metrics_standard():
    # Simulate a nice linear uptrend with a 10% drawdown
    equity = pd.Series([
        1000.0, 
        1050.0, # +5%
        1102.5, # +5%
        992.25, # -10% -> Max DD
        1091.47, # +10%
        1200.62  # +10% -> Total Return ~20%
    ])
    
    # We pass an explicit DatetimeIndex to test Annualization
    dates = pd.date_range(start="2023-01-01", periods=6, freq="D")
    equity.index = dates
    
    metrics = PerformanceMetrics.calculate_equity_metrics(equity)
    
    # Total return 1200.62 / 1000 - 1 = ~20%
    assert round(metrics['total_return_pct'], 2) == 20.06
    
    # Max DD is exactly 10% (from 1102.5 down to 992.25)
    assert round(metrics['max_drawdown_pct'], 2) == -10.0
    
    # Check Ratios exist and are positive
    assert metrics['annualized_return_pct'] > 0
    assert metrics['sharpe_ratio'] > 0
    assert metrics['sortino_ratio'] > 0
    assert metrics['calmar_ratio'] > 0

def test_equity_metrics_flat_line():
    """Flat equity shouldn't crash with division by zero."""
    equity = pd.Series([1000.0, 1000.0, 1000.0, 1000.0])
    metrics = PerformanceMetrics.calculate_equity_metrics(equity)
    
    assert metrics['total_return_pct'] == 0.0
    assert metrics['annualized_return_pct'] == 0.0
    assert metrics['max_drawdown_pct'] == 0.0
    assert metrics['sharpe_ratio'] == 0.0
    assert metrics['sortino_ratio'] == 0.0
    assert metrics['calmar_ratio'] == 0.0

def test_trade_metrics_standard():
    opened = [
        datetime(2023, 1, 1, 10, 0).isoformat(),
        datetime(2023, 1, 2, 10, 0).isoformat(),
        datetime(2023, 1, 3, 10, 0).isoformat()
    ]
    
    closed = [
        datetime(2023, 1, 1, 10, 30).isoformat(), # 30 mins
        datetime(2023, 1, 2, 11, 0).isoformat(),  # 60 mins
        datetime(2023, 1, 3, 10, 45).isoformat()  # 45 mins
    ]
    
    trades = [
        {"net_pnl": 50.0, "opened_at": opened[0], "closed_at": closed[0]},  # Win
        {"net_pnl": -25.0, "opened_at": opened[1], "closed_at": closed[1]}, # Loss
        {"net_pnl": 100.0, "opened_at": opened[2], "closed_at": closed[2]}  # Win
    ]
    
    metrics = PerformanceMetrics.calculate_trade_metrics(trades)
    
    assert metrics['total_trades'] == 3
    assert round(metrics['win_rate_pct'], 2) == 66.67
    assert metrics['average_win'] == 75.0  # (50 + 100) / 2
    assert metrics['average_loss'] == -25.0
    
    # Profit Factor: Gross Profit (150) / Absolute Gross Loss (25) = 6.0
    assert metrics['profit_factor'] == 6.0
    
    # Expectancy: (0.6667 * 75) + (0.3333 * -25) = 50 - 8.333 = 41.67
    assert round(metrics['expectancy'], 2) == 41.67
    
    # Average Duration: (30 + 60 + 45) / 3 = 45.0
    assert metrics['average_duration_minutes'] == 45.0

def test_trade_metrics_perfect_wins():
    """No losing trades shouldn't crash Profit Factor calculation."""
    trades = [
        {"net_pnl": 50.0},
        {"net_pnl": 100.0}
    ]
    metrics = PerformanceMetrics.calculate_trade_metrics(trades)
    
    assert metrics['win_rate_pct'] == 100.0
    assert metrics['profit_factor'] == np.inf
    assert metrics['average_loss'] == 0.0
    assert metrics['expectancy'] == 75.0

def test_empty_inputs():
    """Empty inputs should gracefully return 0.0s, not errors."""
    equity_metrics = PerformanceMetrics.calculate_equity_metrics(pd.Series([]))
    assert equity_metrics['total_return_pct'] == 0.0
    
    trade_metrics = PerformanceMetrics.calculate_trade_metrics([])
    assert trade_metrics['total_trades'] == 0
