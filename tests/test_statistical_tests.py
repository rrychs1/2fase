import pytest
import numpy as np
from analysis.statistical_tests import StatisticalOverfittingTests


def test_generate_block_bootstrap():
    np.random.seed(42)
    returns = np.arange(10)
    bootstrapped = StatisticalOverfittingTests.generate_block_bootstrap(
        returns, block_size=3, n_bootstraps=2
    )

    assert bootstrapped.shape == (2, 10)
    # Check if a block of 3 is preserved
    # At least some difference of consecutive elements should be 1
    diffs = np.diff(bootstrapped[0])
    assert np.any(diffs == 1)


def test_deflated_sharpe_ratio_noise():
    np.random.seed(42)
    # Total garbage noise
    returns = np.random.normal(0, 0.01, 1000)

    dsr = StatisticalOverfittingTests.calculate_deflated_sharpe_ratio(
        returns, n_trials=100, var_trials=0.5
    )

    # Should be overwhelmingly likely to be pure luck (p-value high)
    assert dsr["psr_p_value"] > 0.05


def test_deflated_sharpe_ratio_edge():
    np.random.seed(42)
    # Massive edge
    returns = np.random.normal(0.05, 0.01, 1000)

    dsr = StatisticalOverfittingTests.calculate_deflated_sharpe_ratio(
        returns, n_trials=10, var_trials=0.1
    )

    # With that much edge and low variance/trials, it's very genuine
    assert dsr["psr_p_value"] < 0.05


def test_handsens_spa_and_wrc():
    np.random.seed(42)
    # Guaranteed winning strategy
    strategy = np.random.normal(0.02, 0.01, 500)
    benchmark = np.random.normal(0.00, 0.01, 500)

    spa = StatisticalOverfittingTests.hansens_spa(
        strategy, benchmark, n_bootstraps=500, block_size=2
    )

    # Excellent p-values
    assert spa["spa_p_value"] < 0.05
    assert spa["wrc_p_value"] < 0.05


def test_p_value_bootstrap():
    np.random.seed(42)
    # Garbage strategy
    strategy = np.random.normal(-0.01, 0.02, 500)
    p_val = StatisticalOverfittingTests.calculate_p_value_bootstrap(
        strategy, n_bootstraps=500, block_size=2
    )
    assert p_val == 1.0  # Immediately returns 1.0 for negative edge
