import pytest
import pandas as pd
import numpy as np
from analysis.cross_validation import TimeSeriesCrossValidator


def mock_execute_func(train_df, test_df, params):
    # Generates fake trades. Number of trades = len(test_df)
    if len(test_df) == 0:
        return []

    trades = []
    # If param 'magic' == 1, all trades are wins. Else, mixed.
    win_amount = 100.0 if params.get("magic", 0) == 1 else -10.0

    for i in range(len(test_df)):
        trades.append({"net_pnl": win_amount})

    return trades


def test_generate_folds_expanding():
    df = pd.DataFrame({"close": range(100)})

    # 100 bars. 4 splits. purge = 2
    # dataset_size = 100 - (2*4) = 92
    # test_size = 92 // 5 = 18
    # Folds expanding:
    # 1: Train 0:18, Test 20:38
    # 2: Train 0:36, Test 38:56

    folds = TimeSeriesCrossValidator.generate_folds(
        df, n_splits=4, mode="expanding", purge_bars=2
    )
    assert len(folds) >= 3  # Integer math might drop the 4th if bounds hit

    first_train, first_test = folds[0]
    train_end = len(first_train)

    # Assert purge gap exists
    assert first_train.index[-1] < first_test.index[0]
    # Purge is strictly respected (gap between end of train and start of test)
    assert first_test.index[0] - first_train.index[-1] > 2


def test_generate_folds_rolling():
    df = pd.DataFrame({"close": range(100)})
    folds = TimeSeriesCrossValidator.generate_folds(
        df, n_splits=2, mode="rolling", purge_bars=0
    )

    # 100 // 3 = 33 test size
    # Fold 1: Train 0:33, Test 33:66
    # Fold 2: Train 33:66, Test 66:100 (if remainder pushed to end)

    # We mainly test that the rolling train window shifts
    f1_train, f1_test = folds[0]
    f2_train, f2_test = folds[1]

    assert f1_train.index[0] == 0
    assert f2_train.index[0] > 0  # Rolling starts later!


def test_aggregation_weighting():
    # Setup two mock tearsheets representing different folds
    ts = [
        {"total_trades": 100, "total_return_pct": 10.0, "sharpe_ratio": 2.0},
        {"total_trades": 10, "total_return_pct": -5.0, "sharpe_ratio": -1.0},
    ]

    # Weighting by trades should highly favor the 100 trade fold
    res = TimeSeriesCrossValidator.aggregate_metrics(ts, weighting="trades")

    # weighted mean return = (100 * 10 + 10 * -5) / 110 = 950 / 110 = 8.63% (Not 2.5% simple average!)
    assert round(res["total_return_pct_mean"], 2) == 8.64
    assert res["worst_fold_return_pct"] == -5.0
    assert res["best_fold_return_pct"] == 10.0
