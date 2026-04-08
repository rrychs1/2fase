import pytest
import pandas as pd
import numpy as np
from analysis.risk_metrics import RiskMetrics


def test_rolling_drawdown():
    equity = pd.Series([100.0, 110.0, 99.0, 115.0, 115.0, 103.5])
    dd = RiskMetrics.calculate_rolling_drawdown(equity)

    # 100 -> 0%
    assert dd.iloc[0] == 0.0
    # 110 -> peak -> 0%
    assert dd.iloc[1] == 0.0
    # 99 -> from 110 -> (99-110)/110 = -10%
    assert round(dd.iloc[2], 2) == -0.10
    # 115 -> new peak -> 0%
    assert dd.iloc[3] == 0.0
    # 115 -> flat peak -> 0%
    assert dd.iloc[4] == 0.0
    # 103.5 -> from 115 -> (103.5-115)/115 = -10%
    assert round(dd.iloc[5], 2) == -0.10


def test_monte_carlo_winning_strategy():
    np.random.seed(42)  # For deterministic tests

    # 60% win rate, 2:1 RR (+2% win, -1% loss)
    # This is a highly profitable strategy, Risk of Ruin should be 0.
    trade_returns = [0.02, 0.02, 0.02, -0.01, -0.01]

    curves = RiskMetrics.run_monte_carlo_simulation(
        trade_returns, initial_equity=1000.0, num_simulations=500, sequence_length=100
    )

    # 500 simulations, 101 periods (initial + 100 trades)
    assert curves.shape == (500, 101)

    stats = RiskMetrics.calculate_monte_carlo_statistics(
        curves, 1000.0, ruin_threshold_pct=0.5
    )

    # Positive expectancy strategy should have a strong median return
    assert stats["mc_median_return_pct"] > 50.0
    # Probability of ruin for this setup should be 0
    assert stats["mc_probability_of_ruin_pct"] == 0.0


def test_monte_carlo_losing_strategy():
    np.random.seed(42)
    # Guaranteed losing strategy (-5% every trade)
    trade_returns = [-0.05, -0.05, -0.05]

    curves = RiskMetrics.run_monte_carlo_simulation(
        trade_returns, initial_equity=1000.0, num_simulations=100, sequence_length=20
    )

    # 20 losses at -5% will definitely hit the 50% ruin threshold
    # 0.95^15 = 0.46 (ruined after 15 trades)
    stats = RiskMetrics.calculate_monte_carlo_statistics(
        curves, 1000.0, ruin_threshold_pct=0.5
    )

    assert stats["mc_probability_of_ruin_pct"] == 100.0
    assert stats["mc_median_return_pct"] < 0.0
    assert stats["mc_expected_max_drawdown_pct"] < -50.0


def test_empty_monte_carlo():
    curves = RiskMetrics.run_monte_carlo_simulation([])
    assert curves.shape == (1, 0)

    stats = RiskMetrics.calculate_monte_carlo_statistics(curves, 1000.0)
    assert stats["mc_median_return_pct"] == 0.0


def test_monte_carlo_efficiency():
    import time

    # Stress test: 10,000 simulations, 500 sequence length
    trade_returns = np.random.normal(0.001, 0.02, 500)

    start_time = time.time()
    curves = RiskMetrics.run_monte_carlo_simulation(
        trade_returns, num_simulations=10000, sequence_length=500
    )
    duration = time.time() - start_time

    assert curves.shape == (10000, 501)
    # Vectorized numpy should handle this in < 0.5s on most systems
    assert duration < 1.0


def test_monte_carlo_resampling_logic():
    # If we only provide ONE trade return, every step in every curve MUST be that return
    trade_returns = [0.05]  # +5%
    curves = RiskMetrics.run_monte_carlo_simulation(
        trade_returns, initial_equity=100.0, num_simulations=10, sequence_length=3
    )

    # Sequence: 100 -> 105 -> 110.25 -> 115.7625
    expected_sequence = [100.0, 105.0, 110.25, 115.7625]
    for i in range(10):
        assert np.allclose(curves[i], expected_sequence)


def test_monte_carlo_statistical_accuracy():
    np.random.seed(42)
    # Simple coin flip strategy: 50% chance of +10%, 50% chance of -10%
    # Expected median return for a long enough sequence should be slightly negative
    # due to volatility drag: (1.1 * 0.9)^n = 0.99^n
    trade_returns = [0.10, -0.10]

    curves = RiskMetrics.run_monte_carlo_simulation(
        trade_returns, initial_equity=1000.0, num_simulations=10000, sequence_length=20
    )

    stats = RiskMetrics.calculate_monte_carlo_statistics(curves, 1000.0)

    # Expected median return: 0.99^10 - 1 = -9.56%
    # With 10,000 runs, it should be very close
    assert -12.0 < stats["mc_median_return_pct"] < -7.0

    # 95% Drawdown should be significantly worse than the median drawdown
    assert (
        stats["mc_95_percentile_drawdown_pct"] < stats["mc_expected_max_drawdown_pct"]
    )

    # Worst case should be around (0.9)^20 - 1 = -87.8%
    assert stats["mc_worst_case_return_pct"] < -80.0
