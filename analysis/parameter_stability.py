import pandas as pd
import numpy as np
import logging
import itertools
from typing import Dict, List, Callable, Any

logger = logging.getLogger(__name__)

class ParameterStabilityAnalyzer:
    """
    Evaluates strategy performance across dimensional parameter surfaces to detect curve-fitting 
    cliffs using neighbor-gradients and curvature metrics.
    """
    
    @staticmethod
    def generate_performance_surface(df: pd.DataFrame, execute_func: Callable[[pd.DataFrame, dict], dict], param_grid: Dict[str, list]) -> pd.DataFrame:
        """
        Evaluates the strategy tearsheet across the entire combinatoric parameter grid.
        Returns a DataFrame representing an N-Dimensional Performance Surface.
        Execute_func must accept (df, params) and return a dict tearsheet.
        """
        keys = param_grid.keys()
        values = param_grid.values()
        combinations = [dict(zip(keys, v)) for v in itertools.product(*values)]
        
        results = []
        for params in combinations:
            try:
                ts = execute_func(df, params)
                row = {**params, **ts}
                results.append(row)
            except Exception as e:
                logger.debug(f"Failed simulating param {params}: {e}")
                
        return pd.DataFrame(results)

    @staticmethod
    def calculate_stability_score(surface_df: pd.DataFrame, param_cols: List[str], metric: str = 'sharpe_ratio', radius: int = 1) -> dict:
        """
        Calculates local gradient and curvature for the optimal parameter set to flag isolated 'spikes'.
        Assumes ordinal indexing across param dimensions to establish neighbor distances.
        """
        if surface_df.empty or metric not in surface_df.columns:
            return {}
            
        df_eval = surface_df.copy()
            
        # Rank parameter values assigning integer coordinate bounds to universally map neighbors
        grid_coords = {}
        for p in param_cols:
            if p in df_eval.columns:
                unique_vals = sorted(df_eval[p].unique())
                val_to_idx = {v: i for i, v in enumerate(unique_vals)}
                df_eval[f"{p}_idx"] = df_eval[p].map(val_to_idx)
                grid_coords[p] = f"{p}_idx"
            
        # Find the global optimum for the requested metric
        if df_eval[metric].isna().all():
            return {}
            
        best_idx = df_eval[metric].idxmax()
        best_row = df_eval.loc[best_idx]
        best_val = best_row[metric]
        best_params = {p: best_row[p] for p in param_cols if p in best_row}
        
        # Find neighbors within radius (L-infinity multidimensional bounds)
        neighbor_mask = pd.Series(True, index=df_eval.index)
        for p, p_idx_col in grid_coords.items():
            target_idx = best_row[p_idx_col]
            neighbor_mask &= (df_eval[p_idx_col] >= target_idx - radius) & (df_eval[p_idx_col] <= target_idx + radius)
            
        neighbors_df = df_eval[neighbor_mask]
        
        # Metrics defined over the local neighborhood
        neighbor_vals = neighbors_df[metric].dropna()
        
        if len(neighbor_vals) <= 1:
            local_gradient = 0.0
            neighborhood_variance = 0.0
            stability_score = 0.0
        else:
            # Gradient: average deviation of the peak from its immediate topological neighbors
            local_gradient = float(np.mean(np.abs(best_val - neighbor_vals)))
            # Curvature approximation using variance
            neighborhood_variance = float(np.var(neighbor_vals))
            
            # Formular: Higher peak yields higher score, but steep topological declines erode it
            stability_score = float(best_val / (1.0 + local_gradient + neighborhood_variance))
            
        return {
            "optimal_parameters": best_params,
            f"optimal_{metric}": float(best_val),
            f"{metric}_local_gradient": local_gradient,
            f"{metric}_neighborhood_variance": neighborhood_variance,
            "stability_score": stability_score,
            "neighborhood_size": len(neighbor_vals)
        }
        
    @staticmethod
    def slice_surface(surface_df: pd.DataFrame, fixed_params: Dict[str, Any]) -> pd.DataFrame:
        """
        Slices a N-Dimensional surface down into a 2D plane by fixing extraneous dimensions.
        Produces tabular outputs directly usable by heatmap visualizations.
        """
        sliced_df = surface_df.copy()
        for p, val in fixed_params.items():
            if p in sliced_df.columns:
                sliced_df = sliced_df[sliced_df[p] == val]
        return sliced_df
