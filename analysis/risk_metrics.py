import numpy as np
import pandas as pd
from typing import Dict, Union, List


class RiskMetrics:
    """
    Advanced Risk Analytics and Monte Carlo simulation engine.
    Computes Drawdowns, Volatility limits, and Probabilistic Risk of Ruin.
    """

    @staticmethod
    def calculate_rolling_drawdown(equity_series: pd.Series) -> pd.Series:
        """Calculates the rolling drawdown curve over time."""
        if not isinstance(equity_series, pd.Series):
            equity_series = pd.Series(equity_series)
        rolling_max = equity_series.cummax()
        drawdowns = (equity_series - rolling_max) / rolling_max
        return drawdowns

    @staticmethod
    def calculate_downside_deviation(
        returns: pd.Series, risk_free_rate: float = 0.0
    ) -> float:
        """Calculates downside deviation (Sortino denominator)."""
        if not isinstance(returns, pd.Series):
            returns = pd.Series(returns)
        downside = returns[returns < risk_free_rate] - risk_free_rate
        if len(downside) == 0:
            return 0.0
        return float(np.sqrt(np.mean(downside**2)))

    @staticmethod
    def calculate_volatility(
        returns: pd.Series, annualization_factor: int = 365
    ) -> float:
        """Calculates standard volatility (Sharpe denominator)."""
        if not isinstance(returns, pd.Series):
            returns = pd.Series(returns)
        return float(returns.std() * np.sqrt(annualization_factor))

    @staticmethod
    def run_monte_carlo_simulation(
        trade_returns_pct: Union[List[float], pd.Series, np.ndarray],
        initial_equity: float = 10000.0,
        num_simulations: int = 10000,
        sequence_length: int = None,
    ) -> np.ndarray:
        """
        Runs a Vectorized Monte Carlo simulation using bootstrap resampling.
        Returns a 2D array of simulated equity curves.
        Shape: (num_simulations, sequence_length + 1)
        """
        returns_array = np.array(trade_returns_pct)
        if len(returns_array) == 0:
            return np.array([[]])

        if sequence_length is None:
            sequence_length = len(returns_array)

        # 1. Bootstrap Resampling (Sampling with replacement)
        # Generates a matrix of shape (num_simulations, sequence_length)
        random_indices = np.random.randint(
            0, len(returns_array), size=(num_simulations, sequence_length)
        )
        sampled_returns = returns_array[random_indices]

        # 2. Vectorized compounded equity curve generation using Log Returns for numeric stability
        log_returns = np.log1p(sampled_returns)
        cum_log_returns = np.cumsum(log_returns, axis=1)

        # Convert back to nominal equity
        simulated_equity = initial_equity * np.exp(cum_log_returns)

        # 3. Prepend the initial equity to state 0 of all curves
        initial_column = np.full((num_simulations, 1), initial_equity)
        equity_curves = np.hstack((initial_column, simulated_equity))

        return equity_curves

    @staticmethod
    def calculate_monte_carlo_statistics(
        equity_curves: np.ndarray,
        initial_equity: float,
        ruin_threshold_pct: float = 0.5,  # Defines ruin as losing 50% of account
    ) -> Dict[str, float]:
        """
        Calculates distribution statistics (Confidence Intervals) from Monte Carlo runs.
        """
        if equity_curves.size == 0 or equity_curves.shape[1] < 2:
            return RiskMetrics._empty_mc_stats()

        # Final endpoint of each simulation
        final_equities = equity_curves[:, -1]
        simulated_returns = (final_equities / initial_equity) - 1.0

        median_return = float(np.median(simulated_returns))
        worst_case_return = float(np.min(simulated_returns))

        # Vectorized Drawdown calculation across ALL 10,000 curves simultaneously
        rolling_maxes = np.maximum.accumulate(equity_curves, axis=1)
        drawdowns = (equity_curves - rolling_maxes) / rolling_maxes
        max_drawdowns = np.min(drawdowns, axis=1)  # min because drawdowns are negative

        # Statistics of the drawdowns
        expected_max_drawdown = float(np.median(max_drawdowns))
        expected_95_drawdown = float(
            np.percentile(max_drawdowns, 5)
        )  # 5th percentile is the 95% Confidence worse-case

        # Probability of Ruin
        ruin_level = initial_equity * (1.0 - ruin_threshold_pct)
        # Identify if ANY point in the simulation sequence dipped below the ruin level
        ruined_simulations = np.any(equity_curves <= ruin_level, axis=1)
        probability_of_ruin = float(np.mean(ruined_simulations))

        return {
            "mc_median_return_pct": median_return * 100,
            "mc_worst_case_return_pct": worst_case_return * 100,
            "mc_expected_max_drawdown_pct": expected_max_drawdown * 100,
            "mc_95_percentile_drawdown_pct": expected_95_drawdown * 100,
            "mc_probability_of_ruin_pct": probability_of_ruin * 100,
        }

    @staticmethod
    def _empty_mc_stats() -> dict:
        return {
            "mc_median_return_pct": 0.0,
            "mc_worst_case_return_pct": 0.0,
            "mc_expected_max_drawdown_pct": 0.0,
            "mc_95_percentile_drawdown_pct": 0.0,
            "mc_probability_of_ruin_pct": 0.0,
        }
