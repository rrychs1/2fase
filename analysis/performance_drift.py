import pandas as pd
import numpy as np
import scipy.stats as stats
from typing import Dict, Union, List
from analysis.rolling_metrics import RollingPerformanceMetrics

class PerformanceDriftDetector:
    """
    Detects structural decay (Concept Drift) in trading strategies by comparing 
    recent rolling metrics against extending or rolling historical baselines.
    Supports Z-Scores (parametric) and Percentiles (non-parametric).
    """

    @staticmethod
    def calculate_drift(
        trades_df: pd.DataFrame,
        recent_window: int = 50,
        historical_baseline_window: int = 500, # If None, expanding
        min_trades: int = 100,
        use_percentiles: bool = True,
        weights: dict = None
    ) -> dict:
        """
        Evaluates the strategy's recent edge against its historical performance.
        """
        if len(trades_df) < min_trades or len(trades_df) <= recent_window:
            return {"classification": "INSUFFICIENT_DATA"}
            
        if weights is None:
            weights = {
                'rolling_sharpe': 0.35,
                'rolling_win_rate': 0.20,
                'rolling_profit_factor': 0.25,
                'current_drawdown_pnl': 0.20 # For DD, lower is better. Must invert calculation.
            }
            
        # 1. Compute rolling metrics over the shortest timescale to get high granularity
        # Using a smooth window to prevent singular trade spikes from polluting distributions
        granular_window = max(5, recent_window // 5)
        rolling_df = RollingPerformanceMetrics.calculate_rolling_metrics(trades_df, window=granular_window, min_periods=5)
        rolling_df.dropna(subset=['rolling_pnl_sum'], inplace=True)
        
        if len(rolling_df) < recent_window + 10:
            return {"classification": "INSUFFICIENT_DATA"}
            
        # 2. Split Historical Baseline vs Recent
        recent_block = rolling_df.iloc[-recent_window:]
        
        if historical_baseline_window and len(rolling_df) > historical_baseline_window + recent_window:
            history_block = rolling_df.iloc[-(historical_baseline_window + recent_window) : -recent_window]
        else:
            history_block = rolling_df.iloc[:-recent_window]
            
        # 3. Calculate recent averages (the signal)
        recent_signal = {
            'rolling_sharpe': recent_block['rolling_sharpe'].mean(),
            'rolling_win_rate': recent_block['rolling_win_rate'].mean(),
            'rolling_profit_factor': recent_block['rolling_profit_factor'].mean(),
            'current_drawdown_pnl': recent_block['current_drawdown_pnl'].mean()
        }
        
        scores = {}
        total_drift_score = 0.0
        weight_sum = 0.0
        
        for metric, weight in weights.items():
            if metric not in history_block.columns or history_block[metric].isna().all():
                continue
                
            hist_series = history_block[metric].dropna()
            if len(hist_series) < 10:
                continue
                
            recent_val = recent_signal[metric]
            is_inverted_metric = (metric == 'current_drawdown_pnl')
            
            if use_percentiles:
                # Non-parametric: What % of history was WORSE than our recent value?
                # For Sharpe: If recent=2, and 90% of history is < 2, percentile is 0.90. (High is good)
                # For Drawdown: If recent=100, and 90% of history is < 100, percentile is 0.90. (High is BAD, must invert)
                pct_rank = stats.percentileofscore(hist_series, recent_val) / 100.0
                
                if is_inverted_metric:
                    score = 1.0 - pct_rank # 90% DD --> 0.10 score
                else:
                    score = pct_rank # 90% Sharpe -> 0.90 score
                    
                # Map 0 to 1 back to pseudo Z-scores to maintain backward compatibility of warning bands
                # e.g., pct_rank 0.5 -> score 0. pct_rank 0.158 -> score -1. pct_rank 0.022 -> score -2
                pseudo_z = stats.norm.ppf(max(0.0001, min(0.9999, score))) 
                scores[f"{metric}_zscore"] = pseudo_z
                total_drift_score += pseudo_z * weight
                
            else:
                # Parametric Z-Score
                hist_mean = hist_series.mean()
                hist_std = hist_series.std()
                
                if hist_std == 0:
                    z = 0.0
                else:
                    z = (recent_val - hist_mean) / hist_std
                    if is_inverted_metric:
                        z = -z
                        
                scores[f"{metric}_zscore"] = z
                total_drift_score += z * weight
                
            weight_sum += weight
            
        if weight_sum > 0:
            final_score = total_drift_score / weight_sum
        else:
            final_score = 0.0
            
        classification = "NORMAL"
        if final_score < -2.5:
            classification = "CRITICAL"
        elif final_score < -1.5:
            classification = "WARNING"
            
        return {
            "classification": classification,
            "drift_score_z": float(final_score),
            "recent_metrics": recent_signal,
            "metric_zscores": scores
        }
