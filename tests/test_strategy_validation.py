import pytest
import pandas as pd
from unittest.mock import patch

from validation.strategy_pipeline import StrategyValidationPipeline

@pytest.fixture
def mock_wfa_pass():
    # run_walk_forward returns: (oos_trades, tearsheet)
    tearsheet = {
        "sharpe_ratio": 2.5,
        "max_drawdown_pct": 5.0,
        "win_rate_pct": 80.0,
        "total_pnl": 500.0
    }
    trades = [{"net_pnl": 50}]
    return trades, tearsheet

@pytest.fixture
def mock_wfa_fail_pnl():
    tearsheet = {
        "sharpe_ratio": -0.5,
        "max_drawdown_pct": 15.0,
        "win_rate_pct": 20.0,
        "total_pnl": -100.0
    }
    trades = [{"net_pnl": -100}]
    return trades, tearsheet

@pytest.fixture
def mock_wfa_fail_drift():
    # Drift triggers if sharpe is terribly low (<0.5)
    tearsheet = {
        "sharpe_ratio": 0.2,
        "max_drawdown_pct": 8.0,
        "win_rate_pct": 40.0,
        "total_pnl": 50.0
    }
    trades = [{"net_pnl": 50}]
    return trades, tearsheet

def test_pipeline_pass_stable(mock_wfa_pass):
    pipeline = StrategyValidationPipeline()
    
    with patch('validation.strategy_pipeline.load_historical') as mock_load:
        mock_load.return_value = pd.DataFrame({'close': range(600)})
        
        with patch('validation.strategy_pipeline.WalkForwardValidator.run_walk_forward') as mock_wfa:
            mock_wfa.return_value = mock_wfa_pass
            
            result = pipeline.run_all("Test Strategy")
            
            assert result['is_valid'] is True
            assert "securely" in result['reason']

def test_pipeline_fail_negative_oos(mock_wfa_fail_pnl):
    pipeline = StrategyValidationPipeline()
    
    with patch('validation.strategy_pipeline.load_historical') as mock_load:
        mock_load.return_value = pd.DataFrame({'close': range(600)})
        
        with patch('validation.strategy_pipeline.WalkForwardValidator.run_walk_forward') as mock_wfa:
            mock_wfa.return_value = mock_wfa_fail_pnl
            
            result = pipeline.run_all("Test Strategy")
            
            assert result['is_valid'] is False
            assert "Negative Aggregated" in result['reason']

def test_pipeline_fail_performance_drift(mock_wfa_fail_drift):
    pipeline = StrategyValidationPipeline()
    
    with patch('validation.strategy_pipeline.load_historical') as mock_load:
        mock_load.return_value = pd.DataFrame({'close': range(600)})
        
        with patch('validation.strategy_pipeline.WalkForwardValidator.run_walk_forward') as mock_wfa:
            mock_wfa.return_value = mock_wfa_fail_drift
            
            result = pipeline.run_all("Test Strategy")
            
            assert result['is_valid'] is False
            assert "Unacceptable Aggregated WFA OOS Sharpe" in result['reason']
