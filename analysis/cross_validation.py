import pandas as pd
import numpy as np
import logging
from typing import List, Tuple, Callable, Dict
from analysis.evaluation_framework import StrategyEvaluator

logger = logging.getLogger(__name__)

class TimeSeriesCrossValidator:
    """
    Financial ML Time-Series Cross Validator supporting expanding/rolling windows and Combinatorial Purging.
    """
    
    @staticmethod
    def generate_folds(df: pd.DataFrame, n_splits: int, mode: str = 'expanding', purge_bars: int = 0) -> List[Tuple[pd.DataFrame, pd.DataFrame]]:
        """
        Generates sequentially overlapping or rolling time-series folds, with optional Combinatorial Purged gaps.
        """
        n_samples = len(df)
        if n_splits < 2:
            logger.warning("n_splits must be at least 2")
            return []
            
        dataset_size = n_samples - (purge_bars * n_splits)
        if dataset_size <= 0:
            logger.warning("Dataset too small for given splits and purges.")
            return []
            
        test_size = dataset_size // (n_splits + 1)
        if test_size == 0:
            return []
            
        folds = []
        
        for i in range(1, n_splits + 1):
            if mode == 'expanding':
                train_start = 0
            else: # rolling
                train_start = max(0, (i - 1) * test_size)
                
            train_end = i * test_size
            
            # The purges apply after the train end, before the test block starts
            test_start = train_end + purge_bars
            test_end = test_start + test_size
            
            # If it's the last split, let it consume the rest of the dataframe
            if i == n_splits:
                test_end = n_samples
                
            if test_start >= n_samples:
                break
                
            train_df = df.iloc[train_start:train_end].copy()
            test_df = df.iloc[test_start:test_end].copy()
            
            if not train_df.empty and not test_df.empty:
                folds.append((train_df, test_df))
                
        return folds

    @staticmethod
    def aggregate_metrics(tearsheets: List[Dict], weighting: str = 'trades') -> Dict[str, float]:
        """
        Aggregates multiple tearsheets using weighted means and computes variance for stability scoring.
        Supports 'trades' weighting (folds with more trades count more) or equal weighting.
        """
        if not tearsheets:
            return {}
            
        df = pd.DataFrame(tearsheets)
        
        if weighting == 'trades' and 'total_trades' in df.columns:
            weights = df['total_trades'].fillna(1.0).replace(0, 1.0)
        else:
            weights = pd.Series(np.ones(len(df)))
            
        if weights.sum() == 0:
            weights = pd.Series(np.ones(len(df)))
            
        weights = weights / weights.sum()
        
        aggregated = {}
        metrics_to_agg = [
            'total_return_pct', 'annualized_return_pct', 'sharpe_ratio', 
            'sortino_ratio', 'calmar_ratio', 'win_rate_pct', 'max_drawdown_pct', 
            'profit_factor', 'expectancy'
        ]
        
        for m in metrics_to_agg:
            if m in df.columns:
                series = df[m].fillna(0.0)
                mean_val = np.average(series, weights=weights)
                
                # Weighted variance
                var_val = np.average((series - mean_val)**2, weights=weights)
                
                aggregated[f"{m}_mean"] = float(mean_val)
                aggregated[f"{m}_variance"] = float(var_val)
                
        # Additional robustness stats
        if 'total_return_pct' in df.columns:
            profitable_folds = (df['total_return_pct'] > 0).sum()
            aggregated['profitable_folds_pct'] = float((profitable_folds / len(df)) * 100.0)
            aggregated['worst_fold_return_pct'] = float(df['total_return_pct'].min())
            aggregated['best_fold_return_pct'] = float(df['total_return_pct'].max())
            
        return aggregated

    @staticmethod
    def run_cross_validation(
        df: pd.DataFrame, 
        execute_func: Callable[[pd.DataFrame, pd.DataFrame, dict], List[dict]], 
        params: dict, 
        n_splits: int, 
        mode: str = 'expanding', 
        purge_bars: int = 0, 
        weighting: str = 'trades'
    ) -> Dict:
        """
        Executes strategy evaluation across multiple historical folds and returns weighted robustness metrics.
        The execute_func must accept (train_df, test_df, params) to allow historical ML models to fit on Train and execute on Test.
        """
        folds = TimeSeriesCrossValidator.generate_folds(df, n_splits, mode, purge_bars)
        
        tearsheets = []
        for train_df, test_df in folds:
            try:
                # execution function returns list of trades mapped against Test Data
                trades = execute_func(train_df, test_df, params)
                if trades:
                    trades_df = pd.DataFrame(trades)
                    ts = StrategyEvaluator.evaluate_strategy(trades_df)
                    tearsheets.append(ts)
                else:
                    tearsheets.append(StrategyEvaluator.evaluate_strategy(pd.DataFrame()))
            except Exception as e:
                logger.error(f"CV Fold execution failed: {e}")
                
        return TimeSeriesCrossValidator.aggregate_metrics(tearsheets, weighting)
