import numpy as np
import scipy.stats as stats
import pandas as pd
from typing import Dict, Union, List
import logging

logger = logging.getLogger(__name__)


class StatisticalOverfittingTests:
    """
    Financial Econometrics engine to detect curve-fitting using Block Bootstraps,
    Deflated Sharpe Ratio (with Skew/Kurtosis penalties), and Hansen's SPA.
    """

    @staticmethod
    def generate_block_bootstrap(
        returns: np.ndarray, block_size: int = 5, n_bootstraps: int = 10000
    ) -> np.ndarray:
        """
        Generates Stationary Block Bootstraps to preserve autocorrelation (volatility clustering).
        Returns a 2D array of bootstrapped paths. Shape: (n_bootstraps, len(returns))
        """
        n = len(returns)
        if n == 0 or block_size >= n:
            return np.array([returns] * n_bootstraps) if n > 0 else np.array([])

        n_blocks = int(np.ceil(n / block_size))
        valid_starts = max(1, n - block_size + 1)

        # Matrix of random block starting indices: (n_bootstraps, n_blocks)
        random_starts = np.random.randint(
            0, valid_starts, size=(n_bootstraps, n_blocks)
        )

        offsets = np.arange(block_size)
        # Broadcasting: indices becomes (n_bootstraps, n_blocks, block_size)
        indices = random_starts[..., None] + offsets

        # Flatten blocks into single paths: (n_bootstraps, n_blocks * block_size)
        indices = indices.reshape(n_bootstraps, -1)[:, :n]

        return returns[indices]

    @staticmethod
    def calculate_deflated_sharpe_ratio(
        returns: np.ndarray,
        n_trials: int = 100,
        var_trials: float = 0.5,
        annualization_factor: int = 365,
    ) -> Dict[str, float]:
        """
        Calculates Probabilistic and Deflated Sharpe Ratio using Bailey & Lopez de Prado's theorem.
        Penalizes strategies with negative skewness and high kurtosis (fat tails).
        """
        if len(returns) < 5:
            return {"deflated_sharpe_ratio": 0.0, "psr_p_value": 1.0}

        std_ret = np.std(returns)
        if std_ret == 0:
            return {"deflated_sharpe_ratio": 0.0, "psr_p_value": 1.0}

        mean_ret = np.mean(returns)
        sr_obs = mean_ret / std_ret

        skewness = float(stats.skew(returns))
        kurtosis = float(
            stats.kurtosis(returns, fisher=False)
        )  # Pearson's (normal = 3)

        # Expected Maximum SR under multiple testing
        if n_trials > 1 and var_trials > 0:
            # Approximation of EMSR using bounded distribution
            sr_0 = np.sqrt(var_trials) * np.sqrt(2 * np.log(n_trials))
        else:
            sr_0 = 0.0

        # Variance of the Sharpe Ratio calculation (Lopez de Prado)
        var_sr = 1.0 - (skewness * sr_obs) + (((kurtosis - 1.0) / 4.0) * (sr_obs**2))
        var_sr = max(0.0001, var_sr)  # Prevent negative or zero variance

        n = len(returns)
        dsr_stat = ((sr_obs - sr_0) * np.sqrt(n - 1.0)) / np.sqrt(var_sr)

        # P-value from standard normal CDF
        psr = float(stats.norm.cdf(dsr_stat))
        p_value = 1.0 - psr

        return {
            "observed_sharpe": float(sr_obs * np.sqrt(annualization_factor)),
            "deflated_sharpe": float((sr_obs - sr_0) * np.sqrt(annualization_factor)),
            "psr_p_value": float(p_value),
        }

    @staticmethod
    def hansens_spa(
        strategy_returns: np.ndarray,
        benchmark_returns: np.ndarray = None,
        n_bootstraps: int = 10000,
        block_size: int = 5,
    ) -> Dict[str, float]:
        """
        Hansen's Superior Predictive Ability (SPA) test and White's Reality Check (WRC).
        """
        n = len(strategy_returns)
        if n < 5:
            return {"wrc_p_value": 1.0, "spa_p_value": 1.0}

        if benchmark_returns is None:
            benchmark_returns = np.zeros(n)

        d_k = strategy_returns - benchmark_returns
        d_mean = np.mean(d_k)

        bootstrapped_d = StatisticalOverfittingTests.generate_block_bootstrap(
            d_k, block_size, n_bootstraps
        )

        # WRC approach: strictly center around mean
        wrc_null_dist = np.mean(bootstrapped_d, axis=1) - d_mean

        # Hansen SPA approach: Conditional centering
        d_var = np.var(d_k)
        if d_var == 0:
            return {"wrc_p_value": 1.0, "spa_p_value": 1.0}

        threshold = np.sqrt((d_var * np.log(np.log(n))) / n)
        g_c = d_mean if d_mean >= -threshold else 0.0

        spa_null_dist = np.mean(bootstrapped_d, axis=1) - g_c

        wrc_p_value = float(np.mean(wrc_null_dist >= d_mean))
        spa_p_value = float(np.mean(spa_null_dist >= d_mean))

        return {"wrc_p_value": wrc_p_value, "spa_p_value": spa_p_value}

    @staticmethod
    def calculate_p_value_bootstrap(
        returns: np.ndarray, n_bootstraps: int = 10000, block_size: int = 5
    ) -> float:
        """
        Basic Block Bootstrap hypothesis test against mean = 0.
        """
        n = len(returns)
        if n < 5:
            return 1.0

        obs_mean = np.mean(returns)
        if obs_mean <= 0:
            return 1.0

        # Re-center to 0 (Null hypothesis)
        centered_returns = returns - obs_mean
        bootstrapped = StatisticalOverfittingTests.generate_block_bootstrap(
            centered_returns, block_size, n_bootstraps
        )

        boot_means = np.mean(bootstrapped, axis=1)
        return float(np.mean(boot_means >= obs_mean))

    @staticmethod
    def calculate_overfitting_risk_score(
        dsr_p: float, spa_p: float, boot_p: float
    ) -> float:
        """
        Consolidates the three independent statistical p-values into a single 0-100 Overfitting Risk Score.
        """
        avg_p = (dsr_p + spa_p + boot_p) / 3.0
        worst_p = max(dsr_p, spa_p, boot_p)

        # Weighted mixture favoring the most pessimistic test
        risk_prob = (0.7 * worst_p) + (0.3 * avg_p)

        return float(min(100.0, max(0.0, risk_prob * 100.0)))
