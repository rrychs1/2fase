import pandas as pd
import numpy as np
import logging
import itertools
from typing import List, Tuple, Dict, Callable
from analysis.evaluation_framework import StrategyEvaluator

logger = logging.getLogger(__name__)

class WalkForwardValidator:
    """
    Rolling Walk-Forward Analysis engine to validate trading strategies without lookahead bias.
    Splits data into overlapping Train/Test chronological windows, optimizes parameters in Train,
    and records results strictly from the Out-of-Sample Test periods.
    """
    
    @staticmethod
    def generate_windows(df: pd.DataFrame, train_size: int, test_size: int, step_size: int) -> List[Tuple[pd.DataFrame, pd.DataFrame]]:
        """
        Slices a DataFrame into chronologically strict sequential Train and Test blocks.
        Sizes represent number of rows (bars/candles).
        """
        if len(df) <= train_size + test_size:
            logger.warning("Dataset too small for given train/test sizes.")
            return []
            
        windows = []
        start_idx = 0
        
        while start_idx + train_size + test_size <= len(df):
            train_end = start_idx + train_size
            test_end = train_end + test_size
            
            # Slice by positional index
            train_df = df.iloc[start_idx:train_end].copy()
            test_df = df.iloc[train_end:test_end].copy()
            
            windows.append((train_df, test_df))
            
            # Slide the window forward
            start_idx += step_size
            
        return windows

    @staticmethod
    def optimize_parameters(
        train_df: pd.DataFrame, 
        eval_func: Callable[[pd.DataFrame, dict], float], 
        param_grid: Dict[str, list]
    ) -> dict:
        """
        Runs a grid search over param_grid using eval_func mapping (df, params) -> fitness_score.
        Returns the parameter dictionary that generated the highest score.
        """
        best_score = -np.inf
        best_params = {}
        
        # Unpack grid dict into list of dicts representing all combinations
        keys = param_grid.keys()
        values = param_grid.values()
        combinations = [dict(zip(keys, v)) for v in itertools.product(*values)]
        
        for params in combinations:
            try:
                score = eval_func(train_df, params)
                if score is not None and score > best_score:
                    best_score = score
                    best_params = params
            except Exception as e:
                logger.debug(f"Optimization param {params} failed: {e}")
                pass
                
        return best_params

    @staticmethod
    def run_walk_forward(
        df: pd.DataFrame,
        eval_func: Callable[[pd.DataFrame, dict], float],
        execute_func: Callable[[pd.DataFrame, dict], List[dict]],
        param_grid: Dict[str, list],
        train_size: int,
        test_size: int,
        step_size: int
    ) -> Tuple[List[dict], Dict[str, float]]:
        """
        Executes the entire Walk-Forward validation lifecycle.
        
        Args:
            df: Full historical DataFrame (e.g., OHLCV + required features).
            eval_func: Function to evaluate a param set on train data, returning a fitness float.
            execute_func: Function that simulates trades returning a list of closed trade dicts.
            param_grid: Dictionary of parameter lists to grid-search.
            train_size: Length of training window in rows.
            test_size: Length of testing window in rows.
            step_size: Distance to roll the window forward.
            
        Returns:
            Tuple containing:
            1. List of ALL out-of-sample trades concatenated across all windows.
            2. The final Global Tearsheet containing Risk & Performance stats of those combined OSS trades.
        """
        windows = WalkForwardValidator.generate_windows(df, train_size, test_size, step_size)
        if not windows:
            return [], {}
            
        all_out_of_sample_trades = []
        reports = []
        
        for idx, (train_df, test_df) in enumerate(windows):
            logger.info(f"--- Processing Walk-Forward Window {idx + 1}/{len(windows)} ---")
            
            # 1. Optimize on IN-SAMPLE (Train) Data
            best_params = WalkForwardValidator.optimize_parameters(train_df, eval_func, param_grid)
            logger.info(f"Best IN-SAMPLE params for window {idx + 1}: {best_params}")
            
            # 2. Execute on OUT-OF-SAMPLE (Test) Data blindly using the trained params
            try:
                # The execution returns raw simulated trade ledgers
                oos_trades = execute_func(test_df, best_params)
                all_out_of_sample_trades.extend(oos_trades)
                
                reports.append({
                    "window": idx + 1,
                    "train_start": train_df.index[0] if isinstance(train_df.index, pd.DatetimeIndex) else train_df.iloc[0].name,
                    "train_end": train_df.index[-1] if isinstance(train_df.index, pd.DatetimeIndex) else train_df.iloc[-1].name,
                    "test_start": test_df.index[0] if isinstance(test_df.index, pd.DatetimeIndex) else test_df.iloc[0].name,
                    "test_end": test_df.index[-1] if isinstance(test_df.index, pd.DatetimeIndex) else test_df.iloc[-1].name,
                    "params": best_params,
                    "trades": len(oos_trades)
                })
            except Exception as e:
                logger.error(f"Out-of-sample execution failed for window {idx + 1}: {e}")
                
        # 3. Aggregate results and run through the Evaluation Framework
        if not all_out_of_sample_trades:
            logger.warning("No out-of-sample trades were executed across any window.")
            return [], {}
            
        trades_df = pd.DataFrame(all_out_of_sample_trades)
        
        # Use initial balance 10,000 for standard tearsheet synthetic building
        tearsheet = StrategyEvaluator.evaluate_strategy(trades_df, initial_balance=10000.0)
        
        # Optionally, you can attach the report blocks onto the dictionary to debug timeline splits
        # tearsheet['wfo_windows'] = reports
        return all_out_of_sample_trades, tearsheet
