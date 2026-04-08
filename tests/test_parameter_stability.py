import pytest
import pandas as pd
from analysis.parameter_stability import ParameterStabilityAnalyzer


def mock_surface_execute(df, params):
    # Returns purely a dict with Sharpe based on params
    # Peak at fast=15, slow=30. Others drop off.
    sharpe = 0.0
    if params["fast"] == 15 and params["slow"] == 30:
        sharpe = 10.0  # Sharp Spike Exception
    elif params["fast"] == 14 and params["slow"] == 30:
        sharpe = 0.1  # Very steep dropoff
    else:
        sharpe = params["fast"] * 0.1 + params["slow"] * 0.01  # Broad low plateau

    return {"sharpe_ratio": sharpe, "total_return_pct": sharpe * 10.0}


def test_generate_performance_surface():
    df = pd.DataFrame()
    param_grid = {"fast": [10, 14, 15], "slow": [20, 30]}

    surface = ParameterStabilityAnalyzer.generate_performance_surface(
        df, mock_surface_execute, param_grid
    )

    # 3x2 grid = 6 rows
    assert len(surface) == 6
    assert "sharpe_ratio" in surface.columns

    # Assert peak is captured
    peak = surface.loc[surface["sharpe_ratio"].idxmax()]
    assert peak["fast"] == 15
    assert peak["slow"] == 30
    assert peak["sharpe_ratio"] == 10.0


def test_stability_score():
    data = [
        {"fast": 10, "slow": 20, "sharpe_ratio": 1.0},
        {"fast": 11, "slow": 20, "sharpe_ratio": 1.1},  # Broad Plateau
        {"fast": 12, "slow": 20, "sharpe_ratio": 1.0},
        {"fast": 10, "slow": 30, "sharpe_ratio": 0.0},
        {"fast": 11, "slow": 30, "sharpe_ratio": 5.0},  # Sharp Spike
        {"fast": 12, "slow": 30, "sharpe_ratio": 0.0},
    ]
    df = pd.DataFrame(data)

    # Slice to compute score specifically for the spike neighborhood
    # Note: the algorithm searches globally for idxmax. The max is 5.0 at (11, 30)
    score_dict = ParameterStabilityAnalyzer.calculate_stability_score(
        df, param_cols=["fast", "slow"], metric="sharpe_ratio", radius=1
    )

    # Neighbors of (11, 30) within radius 1 are:
    # (10,30), (12,30), (10,20), (11,20), (12,20)... etc.
    # The gradient should be high because its neighbors drop to 0 or 1.
    assert score_dict["optimal_parameters"]["fast"] == 11
    assert score_dict["sharpe_ratio_local_gradient"] > 1.0  # Significant deviation
    assert (
        score_dict["stability_score"] < 5.0
    )  # Score highly penalized by variance/gradient


def test_slice_surface():
    data = [
        {"fast": 10, "slow": 20, "atr": 1, "sharpe": 1.0},
        {"fast": 10, "slow": 20, "atr": 2, "sharpe": 1.5},
        {"fast": 15, "slow": 30, "atr": 1, "sharpe": 2.0},
    ]
    df = pd.DataFrame(data)

    # Fix ATR = 1
    sliced = ParameterStabilityAnalyzer.slice_surface(df, fixed_params={"atr": 1})

    assert len(sliced) == 2
    assert sliced["sharpe"].sum() == 3.0
