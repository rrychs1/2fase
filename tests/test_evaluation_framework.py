import pytest
import pandas as pd
import json
import os
from analysis.evaluation_framework import StrategyEvaluator


@pytest.fixture
def mock_jsonl_file():
    filepath = "target_test_trades.jsonl"
    trades = [
        {
            "symbol": "BTC",
            "side": "LONG",
            "net_pnl": 100.0,
            "closed_at": "2023-01-01T10:30:00",
        },
        {
            "symbol": "ETH",
            "side": "SHORT",
            "net_pnl": -50.0,
            "closed_at": "2023-01-01T11:45:00",
        },
        {
            "symbol": "BTC",
            "side": "LONG",
            "net_pnl": 200.0,
            "closed_at": "2023-01-01T13:10:00",
        },
    ]
    with open(filepath, "w") as f:
        for t in trades:
            f.write(json.dumps(t) + "\n")
    yield filepath
    if os.path.exists(filepath):
        os.remove(filepath)
    if os.path.exists("test_report.md"):
        os.remove("test_report.md")
    if os.path.exists("test_report.csv"):
        os.remove("test_report.csv")


def test_load_trades_and_evaluate(mock_jsonl_file):
    # Load
    df = StrategyEvaluator.load_trades_from_jsonl(mock_jsonl_file)
    assert len(df) == 3
    assert "net_pnl" in df.columns

    # Generate Synthetic Equity
    eq = StrategyEvaluator.generate_synthetic_equity_curve(df, initial_balance=1000.0)
    # Start: 1000 -> 1100 -> 1050 -> 1250
    assert len(eq) == 4
    assert eq.iloc[-1] == 1250.0

    # Evaluate
    tearsheet = StrategyEvaluator.evaluate_strategy(df, 1000.0)
    assert tearsheet["total_return_pct"] == 25.0
    assert tearsheet["total_trades"] == 3
    assert round(tearsheet["win_rate_pct"], 2) == 66.67

    # Generate Reports
    md = StrategyEvaluator.generate_markdown_report(
        tearsheet, strategy_name="Test Strategy", filepath="test_report.md"
    )
    assert "## Executive Summary" in md
    assert "25.00%" in md
    assert os.path.exists("test_report.md")

    success = StrategyEvaluator.export_to_csv(tearsheet, "test_report.csv")
    assert success
    assert os.path.exists("test_report.csv")

    # Verify CSV content
    csv_df = pd.read_csv("test_report.csv")
    assert len(csv_df) > 10  # Should have lots of metrics
    assert "total_return_pct" in csv_df["Metric"].values
