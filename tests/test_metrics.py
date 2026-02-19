"""Tests for backtesting/metrics.py."""
import pytest
from backtesting.metrics import calculate_metrics, BacktestMetrics
from backtesting.sim_broker import SimTrade


class TestReturnCalculation:
    def test_100_percent_return(self):
        equity_curve = [10000.0] + [20000.0] * 100
        metrics = calculate_metrics(equity_curve, [], 10000.0, 60000.0, 65000.0)
        assert metrics.total_return_pct == 100.0
        assert metrics.total_pnl == 10000.0

    def test_zero_return(self):
        equity_curve = [10000.0] * 100
        metrics = calculate_metrics(equity_curve, [], 10000.0, 60000.0, 60000.0)
        assert metrics.total_return_pct == 0.0

    def test_negative_return(self):
        equity_curve = [10000.0] + [8000.0] * 50
        metrics = calculate_metrics(equity_curve, [], 10000.0, 60000.0, 55000.0)
        assert metrics.total_return_pct == -20.0


class TestSharpeRatio:
    def test_flat_equity_zero_sharpe(self):
        equity_curve = [10000.0] * 100
        metrics = calculate_metrics(equity_curve, [], 10000.0, 60000.0, 60000.0)
        assert metrics.sharpe_ratio == 0.0

    def test_positive_sharpe(self):
        # Steadily increasing equity
        equity_curve = [10000.0 + i * 10 for i in range(100)]
        metrics = calculate_metrics(equity_curve, [], 10000.0, 60000.0, 65000.0)
        assert metrics.sharpe_ratio > 0


class TestMaxDrawdown:
    def test_no_drawdown(self):
        equity_curve = [10000.0 + i for i in range(100)]
        metrics = calculate_metrics(equity_curve, [], 10000.0, 60000.0, 65000.0)
        assert metrics.max_drawdown_pct < 0.1  # Essentially zero

    def test_known_drawdown(self):
        # Peak at 12000, trough at 9000 -> 25% DD
        equity_curve = [10000, 11000, 12000, 10000, 9000, 10000, 11000]
        metrics = calculate_metrics(equity_curve, [], 10000.0, 60000.0, 65000.0)
        assert abs(metrics.max_drawdown_pct - 25.0) < 0.1


class TestTradeStatistics:
    def _make_trades(self):
        return [
            SimTrade("BTC", "LONG", 60000, 62000, 0.1, 200, 195, 5),
            SimTrade("BTC", "LONG", 61000, 60000, 0.1, -100, -103, 3),
            SimTrade("BTC", "SHORT", 63000, 61000, 0.1, 200, 196, 4),
            SimTrade("BTC", "LONG", 60000, 59000, 0.1, -100, -103, 3),
            SimTrade("BTC", "LONG", 59000, 61000, 0.1, 200, 196, 4),
        ]

    def test_win_rate(self):
        trades = self._make_trades()
        metrics = calculate_metrics([10000] * 10, trades, 10000.0, 60000.0, 62000.0)
        # 3 winners out of 5
        assert metrics.win_rate == 60.0

    def test_profit_factor(self):
        trades = self._make_trades()
        metrics = calculate_metrics([10000] * 10, trades, 10000.0, 60000.0, 62000.0)
        # Gross profit = 195 + 196 + 196 = 587
        # Gross loss = 103 + 103 = 206
        expected_pf = 587.0 / 206.0
        assert abs(metrics.profit_factor - expected_pf) < 0.01

    def test_max_consecutive_losses(self):
        trades = [
            SimTrade("BTC", "LONG", 60000, 61000, 0.1, 100, 97, 3),  # win
            SimTrade("BTC", "LONG", 60000, 59000, 0.1, -100, -103, 3),  # loss
            SimTrade("BTC", "LONG", 60000, 59000, 0.1, -100, -103, 3),  # loss
            SimTrade("BTC", "LONG", 60000, 59000, 0.1, -100, -103, 3),  # loss
            SimTrade("BTC", "LONG", 60000, 61000, 0.1, 100, 97, 3),  # win
        ]
        metrics = calculate_metrics([10000] * 10, trades, 10000.0, 60000.0, 61000.0)
        assert metrics.max_consecutive_losses == 3

    def test_no_trades(self):
        metrics = calculate_metrics([10000] * 10, [], 10000.0, 60000.0, 61000.0)
        assert metrics.total_trades == 0
        assert metrics.win_rate == 0.0
        assert metrics.profit_factor == 0.0


class TestBuyAndHold:
    def test_buy_and_hold_return(self):
        metrics = calculate_metrics([10000] * 10, [], 10000.0, 60000.0, 72000.0)
        # (72000 - 60000) / 60000 = 20%
        assert metrics.buy_and_hold_return_pct == 20.0
