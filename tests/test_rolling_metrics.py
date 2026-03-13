import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from analysis.rolling_metrics import RollingPerformanceMetrics

def test_rolling_metrics_count_window():
    # 10 trades, window=5, min_periods=2
    data = {"net_pnl": [10, -5, 10, 10, -10, 20, 20, 20, -5, -5]}
    df = pd.DataFrame(data)
    
    metrics = RollingPerformanceMetrics.calculate_rolling_metrics(df, window=5, min_periods=2, annualize_factor=1)
    
    assert len(metrics) == 10
    assert "rolling_sharpe" in metrics.columns
    assert "rolling_profit_factor" in metrics.columns
    assert "rolling_drawdown_pnl" not in metrics.columns # It's 'current_drawdown_pnl'
    assert "current_drawdown_pnl" in metrics.columns
    
    # First trade is NaN due to min_periods=2
    assert pd.isna(metrics['rolling_win_rate'].iloc[0])
    
    # Second trade: win (10) and loss (-5). Win rate = 0.5
    assert metrics['rolling_win_rate'].iloc[1] == 0.5
    
    # At index 4 (trades 0 to 4): net_pnls are [10, -5, 10, 10, -10]
    # Wins: 3, Losses: 2 => Win Rate = 0.6
    assert metrics['rolling_win_rate'].iloc[4] == 0.6
    
    # Gross Profit = 10+10+10=30, Gross Loss = 5+10=15 => PF = 2.0
    assert metrics['rolling_profit_factor'].iloc[4] == 2.0

    # net_pnls: [10, -5, 10, 10, -10]
    # Mean = 3.0, Var(ddof=1) = 95, Std = 9.74679
    # Sharpe = 3.0 / 9.74679 * sqrt(1) = 0.30779
    assert metrics['rolling_sharpe'].iloc[4] == pytest.approx(0.30779, abs=1e-5)

    # Expectancy Calculation Check
    # Win Rate = 0.6, Loss Rate = 0.4
    # Avg Win = (10+10+10)/3 = 10.0
    # Avg Loss = (5+10)/2 = 7.5
    # Expectancy = (0.6 * 10.0) - (0.4 * 7.5) = 6.0 - 3.0 = 3.0
    assert metrics['rolling_expectancy'].iloc[4] == pytest.approx(3.0)

def test_rolling_metrics_time_window():
    # Time-based window '2d'
    dates = [
        datetime(2023,1,1, 10, 0),
        datetime(2023,1,1, 12, 0), # Same day
        datetime(2023,1,3, 10, 0), # Gap -> Previous trades should roll off
        datetime(2023,1,4, 10, 0)
    ]
    data = {
        "exit_time": dates,
        "net_pnl": [10, 10, -10, -10]
    }
    df = pd.DataFrame(data)
    
    metrics = RollingPerformanceMetrics.calculate_rolling_metrics(df, window='2d', min_periods=1, annualize_factor=1)
    
    # Index 1: both trades are within 2d. Win rate = 1.0
    assert metrics['rolling_win_rate'].iloc[1] == 1.0
    
    # Index 2: Time is Jan 3. The 2 day window goes back to Jan 1, 10:00:00 (exact depends on pandas closed bounds)
    # Actually, pandas '2d' on Jan 3 covers Jan 1 10:00 to Jan 3 10:00. So the first trade might fall out if strictly >
    
def test_rolling_metrics_drawdown():
    # Equity sequence
    data = {"net_pnl": [100, 50, -50, -100, 200, -10]}
    # cumulative_pnl: [100, 150, 100, 0, 200, 190]
    # cummax:         [100, 150, 150, 150, 200, 200]
    # dd:             [0, 0, 50, 150, 0, 10]
    
    df = pd.DataFrame(data)
    metrics = RollingPerformanceMetrics.calculate_rolling_metrics(df, window=3, min_periods=1)
    
    assert metrics['current_drawdown_pnl'].iloc[2] == 50
    assert metrics['current_drawdown_pnl'].iloc[3] == 150
    assert metrics['current_drawdown_pnl'].iloc[5] == 10

def test_profit_factor_zero_division():
    # All wins -> Gross Loss is 0 -> Profit Factor handles Inf
    data = {"net_pnl": [10, 10, 10]}
    df = pd.DataFrame(data)
    metrics = RollingPerformanceMetrics.calculate_rolling_metrics(df, window=3, min_periods=1)
    
    # Without losses, PF should be NaN or handled to avoid crashing
    assert pd.isna(metrics['rolling_profit_factor'].iloc[2])
