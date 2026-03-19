import pytest
import pandas as pd
import numpy as np
import datetime
from unittest.mock import patch, MagicMock

from validation.strategy_pipeline import StrategyValidationPipeline

def create_mock_df(days: int = 360) -> pd.DataFrame:
    """Provides enough mathematical mass to bypass length constraints."""
    dates = pd.date_range(end=datetime.datetime.now(), periods=days * 6, freq="4h")
    df = pd.DataFrame({
        'timestamp': dates,
        'open': np.linspace(50000, 60000, len(dates)),
        'high': np.linspace(50000, 60000, len(dates)) + 100,
        'low': np.linspace(50000, 60000, len(dates)) - 100,
        'close': np.linspace(50000, 60000, len(dates)),
        'volume': np.random.uniform(1, 10, len(dates))
    })
    return df

class TestStrategyPipelineQuantitativeAudit:
    
    @patch('validation.strategy_pipeline.load_historical')
    def test_pipeline_rejects_overfitted_strategy(self, mock_load):
        """
        OVERFIT SCENARIO:
        The strategy generates massive Sharpe ratios recursively on In-Sample (Training) blocks,
        but strictly leaks massive Drawdowns natively Out-Of-Sample (Testing) blocks.
        Result: Pipeline must cleanly block deployment.
        """
        mock_load.return_value = create_mock_df()
        pipeline = StrategyValidationPipeline()
        
        # In-Sample evaluates as a genius
        pipeline._eval_func = MagicMock(return_value=5.5) 
        
        # Out-Of-Sample evaluates as a disaster
        def explosive_loss_trades(test_df, params):
            t1 = test_df.iloc[0]['timestamp'].isoformat()
            t2 = test_df.iloc[-1]['timestamp'].isoformat()
            return [
                {"symbol": "BTC/USDT", "side": "LONG", "net_pnl": -1500.0, "pnl": -1500.0, "realized_pnl": -1500.0, "amount": 1.0, "closed_at": t1},
                {"symbol": "BTC/USDT", "side": "SHORT", "net_pnl": -2000.0, "pnl": -2000.0, "realized_pnl": -2000.0, "amount": 1.0, "closed_at": t2}
            ]
        pipeline._execute_func = explosive_loss_trades
        
        result = pipeline.run_all("MockOverfitGrid")
        print("\n=== OVERFIT RESULT ===")
        print(result)
        
        assert result["is_valid"] is False, "A massive Out-Of-Sample bleeder was erroneously validated!"
        assert result["sharpe"] < 0.5, "Overfitted WFA Sharpe incorrectly padded"
        assert result["stability_score"] < 50.0, "Overfitted Strategy Stability Score incorrectly high"
        assert "Negative Aggregated WFA" in result["reason"] or "Dangerous Aggregated WFA" in result["reason"], "Failed to identify structural PnL damage"


    @patch('validation.strategy_pipeline.load_historical')
    def test_pipeline_accepts_stable_strategy(self, mock_load):
        """
        STABLE SCENARIO:
        Strategy adapts seamlessly cleanly out-of-sample producing steady, 
        consistent fractional yield geometrically proving strict robustness natively.
        Result: Pipeline mathematical bounds must seamlessly Accept.
        """
        mock_load.return_value = create_mock_df()
        pipeline = StrategyValidationPipeline()
        
        # In-Sample evaluates decently
        pipeline._eval_func = MagicMock(return_value=1.5) 
        
        # Out-Of-Sample continues mathematically robust consistency
        def stable_gain_trades(test_df, params):
            mid_idx = len(test_df) // 2
            t1 = test_df.iloc[0]['timestamp'].isoformat()
            t2 = test_df.iloc[mid_idx]['timestamp'].isoformat()
            return [
                {"symbol": "BTC/USDT", "side": "LONG", "net_pnl": 200.0, "pnl": 200.0, "realized_pnl": 200.0, "amount": 0.5, "closed_at": t1},
                {"symbol": "BTC/USDT", "side": "SHORT", "net_pnl": 150.0, "pnl": 150.0, "realized_pnl": 150.0, "amount": 0.5, "closed_at": t2}
            ]
        pipeline._execute_func = stable_gain_trades
        
        result = pipeline.run_all("MockStableDCA")
        print("\n=== STABLE RESULT ===")
        print(result)
        
        # The tearsheet should yield aggregate profit over 12 overlapping slices
        assert result["is_valid"] is True, f"Stable Strategy Unjustly Rejected: {result['reason']}"
        assert result["sharpe"] >= 0.5, f"Stable WFA Sharpe too low: {result['sharpe']}"
        assert result["stability_score"] > 50.0, "Stability Score did not appropriately reward robust tracking metrics"
        assert "Passed" in result["reason"], "Reason incorrectly appended"

    @patch('validation.strategy_pipeline.load_historical')
    def test_pipeline_catches_drawdown_drift(self, mock_load):
        """
        DRIFT SCENARIO:
        Strategy makes absolute money geometrically (PnL > 0, Sharpe > 1.0),
        BUT randomly suffers a single 35% account equity wipeout in window 4 out-of-sample natively.
        Result: Pipeline must mathematically reject the unhandled Risk variance.
        """
        mock_load.return_value = create_mock_df()
        pipeline = StrategyValidationPipeline()
        
        pipeline._eval_func = MagicMock(return_value=2.0)
        
        call_count = 0
        def volatile_drift_trades(test_df, params):
            nonlocal call_count
            call_count += 1
            t1 = test_df.iloc[0]['timestamp'].isoformat()
            if call_count == 4:
                # Disastrous Out-Of-Sample Wipeout (40% of 10k baseline)
                return [{"symbol": "BTC/USDT", "side": "LONG", "net_pnl": -4000.0, "pnl": -4000.0, "realized_pnl": -4000.0, "amount": 2.0, "closed_at": t1}]
            return [{"symbol": "BTC/USDT", "side": "LONG", "net_pnl": 500.0, "pnl": 500.0, "realized_pnl": 500.0, "amount": 0.5, "closed_at": t1}]
            
        pipeline._execute_func = volatile_drift_trades
        
        result = pipeline.run_all("MockDrawdownDrift")
        
        assert result["is_valid"] is False, "A massive localized WFA Drawdown was allowed into production blindly!"
        assert "Dangerous Aggregated WFA Drawdown" in result["reason"], "Failed to identify the sharp Volatility spike explicitly."

