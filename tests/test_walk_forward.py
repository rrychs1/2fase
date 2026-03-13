import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from analysis.walk_forward_engine import WalkForwardValidator

def mock_eval_func(df: pd.DataFrame, params: dict) -> float:
    """Mock fitness function favoring params['fast'] = 10 over anything else."""
    if params.get('fast', 0) == 10:
        return 100.0
    return -10.0

def mock_execute_func(df: pd.DataFrame, params: dict) -> list:
    """Mock execution mimicking one profitable trade of $50 per execution block based on 'fast'=10 parameter success."""
    if params.get('fast', 0) == 10:
        return [{"net_pnl": 50.0, "closed_at": df.index[-1].isoformat()}]
    else:
        # Generate a losing trade if wrong parameters passed
        return [{"net_pnl": -50.0, "closed_at": df.index[-1].isoformat()}]

def test_generate_windows():
    # 100 days of data
    dates = pd.date_range("2023-01-01", periods=100, freq="D")
    df = pd.DataFrame({"close": np.random.randn(100)}, index=dates)
    
    # 30 day train, 10 day test, roll forward 10 days
    # Windows:
    # 0: [0-30] / [30-40]
    # 1: [10-40] / [40-50]
    # ...
    windows = WalkForwardValidator.generate_windows(df, train_size=30, test_size=10, step_size=10)
    
    assert len(windows) == 7 # (100 - (30+10)) / 10 + 1 = 60/10 + 1 = 7
    
    first_train, first_test = windows[0]
    assert len(first_train) == 30
    assert len(first_test) == 10
    
    # Assert chronology integrity (no overlap between a block's train and test)
    assert first_train.index[-1] < first_test.index[0]

def test_optimize_parameters():
    df = pd.DataFrame()
    param_grid = {
        "fast": [5, 10, 15],
        "slow": [20, 30]
    }
    
    best_params = WalkForwardValidator.optimize_parameters(df, mock_eval_func, param_grid)
    
    # The mock eval function strongly favors 'fast' == 10
    assert best_params['fast'] == 10
    # 'slow' defaults to whatever combination hit first since it doesn't matter, usually 20
    assert 'slow' in best_params

def test_run_walk_forward_end_to_end():
    dates = pd.date_range("2023-01-01", periods=60, freq="D")
    df = pd.DataFrame({"close": np.ones(60)}, index=dates)
    
    param_grid = {"fast": [5, 10, 15]}
    
    # For a 60 bar frame:
    # Train 30, test 10, step 10 -> Gives 3 windows
    # Window 0: Train 0:30, Test 30:40
    # Window 1: Train 10:40, Test 40:50
    # Window 2: Train 20:50, Test 50:60
    
    oss_trades, tearsheet = WalkForwardValidator.run_walk_forward(
        df=df,
        eval_func=mock_eval_func,
        execute_func=mock_execute_func,
        param_grid=param_grid,
        train_size=30,
        test_size=10,
        step_size=10
    )
    
    # Expected 3 trades (one per test window chunk) 
    # Because best parameters ('fast': 10) win out in the evaluation phase, 
    # each trade should be +50 PnL
    assert len(oss_trades) == 3
    for t in oss_trades:
        assert t['net_pnl'] == 50.0
        
    # Check the aggregated Tearsheet
    # 3 trades * 50 = $150 Gross. 10,000 Initial balance -> Total Return 1.5%
    assert round(tearsheet['total_return_pct'], 1) == 1.5
    assert tearsheet['win_rate_pct'] == 100.0
    assert tearsheet['total_trades'] == 3
