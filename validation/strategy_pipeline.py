import logging
import pandas as pd
import numpy as np
import datetime
from typing import Dict, List, Tuple

from config.config_loader import Config
from backtesting.data_loader import load_historical
from backtesting.backtest_engine import BacktestEngine
from analysis.walk_forward_engine import WalkForwardValidator

logger = logging.getLogger(__name__)

class StrategyValidationPipeline:
    def __init__(self, symbol: str = "BTC/USDT", timeframe: str = "4h"):
        self.symbol = symbol
        self.timeframe = timeframe
        self.config = Config()

    def _eval_func(self, df: pd.DataFrame, params: dict) -> float:
        """Runs IN-SAMPLE optimization on Train data; returns fitness (Sharpe)."""
        engine = BacktestEngine(symbol=self.symbol, timeframe=self.timeframe, lookback=250)
        # Suppress logging inside the massive WFA grid sweep
        logging.getLogger('backtesting.backtest_engine').setLevel(logging.WARNING)
        
        if params:
            for k, v in params.items():
                setattr(engine.config, k, v)
        metrics = engine.run(df)
        return metrics.sharpe_ratio

    def _execute_func(self, df: pd.DataFrame, params: dict) -> List[dict]:
        """Runs the Test OUT-OF-SAMPLE data with best params blindly; returns trades ledger."""
        engine = BacktestEngine(symbol=self.symbol, timeframe=self.timeframe, lookback=250)
        if params:
            for k, v in params.items():
                setattr(engine.config, k, v)
        engine.run(df)
        
        # Convert internal trade objects cleanly into standard dictionaries for WFA concatenators
        trades = []
        for t in engine.broker.trades:
            if hasattr(t, "to_dict"):
                trades.append(t.to_dict())
            elif hasattr(t, "__dict__"):
                trades.append(t.__dict__)
            elif isinstance(t, dict):
                trades.append(t)
        return trades

    def run_all(self, strategy_name: str) -> Dict:
        """
        Runs the full mandatory Rolling Walk-Forward Analysis (WFA) pipeline.
        Returns a dictionary containing 'is_valid' boolean and performance scores.
        """
        logger.info(f"[Validation Pipeline] Starting Walk-Forward Analysis (WFA) for {strategy_name} on {self.symbol}")
        
        # Load 1 full year of data for robust chronological window rolling
        start_dt = (datetime.datetime.now() - datetime.timedelta(days=360)).strftime("%Y-%m-%d")
        end_dt = datetime.datetime.now().strftime("%Y-%m-%d")
        
        try:
            df = load_historical(self.symbol, self.timeframe, start_date=start_dt, end_date=end_dt)
            if df.empty or len(df) < 500:
                raise ValueError("Dataset empty")
        except Exception:
            df = load_historical(self.symbol, self.timeframe, "2025-01-01", "2026-01-01")
            
        if df.empty or len(df) < 500: # We need minimum rows safely pad the lookback logic
            logger.error("[Validation Pipeline] Insufficient data.")
            return {"is_valid": False, "reason": "Insufficient offline data for WFA chronological validation"}

        # WFA configuration scaling dynamically mapping Timeframes to physical Days conceptually
        CPD = 6  # 4h timeframe candles per day
        train_size = 90 * CPD   # Train on 90 days iteratively
        test_size = 30 * CPD    # Test on exactly the following blind 30 days
        step_size = 30 * CPD    # Roll the chronology forward exactly 1 month
        
        # Matrix configurations to violently assault the Strategy parameters to test mathematical resilience
        param_grid = {
            'GRID_STEP_PCT': [0.008, 0.010, 0.012],
            'TREND_ATR_MULT': [1.8, 2.0, 2.2]
        }
        
        logger.info(f"[Validation Pipeline] WFA Splitting array into windows (Train: {train_size//CPD}d, Test: {test_size//CPD}d)...")
        
        oos_trades, tearsheet = WalkForwardValidator.run_walk_forward(
            df=df,
            eval_func=self._eval_func,
            execute_func=self._execute_func,
            param_grid=param_grid,
            train_size=train_size,
            test_size=test_size,
            step_size=step_size
        )
        
        # Validation Pipeline Fail conditions
        if not oos_trades or not tearsheet:
            return {
                "is_valid": False,
                "reason": "WFA Failed to generate any Out-Of-Sample trades. Strategy functionally barren.",
                "sharpe": 0,
                "stability_score": 0
            }

        wfa_sharpe = tearsheet.get("sharpe_ratio", 0)
        wfa_drawdown = tearsheet.get("max_drawdown_pct", 100.0)
        win_rate = tearsheet.get("win_rate_pct", 0)
        
        # --- FAIL CONDITION A: Negative WFA Combined Out-Of-Sample Performance ---
        if tearsheet.get("total_return_pct", 0) < 0:
            return {
                "is_valid": False,
                "reason": f"Negative Aggregated WFA Performance (Return: {tearsheet.get('total_return_pct', 0):.2f}%)",
                "sharpe": wfa_sharpe,
                "drawdown": wfa_drawdown,
                "stability_score": 0
            }

        # --- FAIL CONDITION B: Dangerous Sequential Out-Of-Sample Drawdown ---
        if wfa_drawdown < -15.0: # Strategy explicitly structurally fails the Hard block at 15% unified OOS drawdown 
            return {
                "is_valid": False,
                "reason": f"Dangerous Aggregated WFA Drawdown ({wfa_drawdown:.1f}%) exceeds safety margin.",
                "sharpe": wfa_sharpe,
                "drawdown": wfa_drawdown,
                "stability_score": min(50, win_rate)
            }
            
        # --- FAIL CONDITION C: Barren Metrics (Low Mathematical Edge across chronological vectors) ---
        if wfa_sharpe < 0.5:
            return {
                "is_valid": False,
                "reason": f"Unacceptable Aggregated WFA OOS Sharpe ({wfa_sharpe:.2f})",
                "sharpe": wfa_sharpe,
                "drawdown": wfa_drawdown,
                "stability_score": min(40, win_rate)
            }

        # WFA essentially proves robust Stability mathematically because it forces the strategy ruleset to adapt seamlessly blind sequentially. 
        stability_score = min(100.0, max(0.0, win_rate * (wfa_sharpe / 1.5)))

        logger.info(f"[Validation Pipeline] {strategy_name} PASSED WFA! Sharpe: {wfa_sharpe:.2f}, Stability: {stability_score:.1f}%")
        return {
            "is_valid": True,
            "reason": "Passed all rolling WFA sequence metrics securely",
            "sharpe": wfa_sharpe,
            "drawdown": wfa_drawdown,
            "stability_score": stability_score
        }
