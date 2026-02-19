"""Tests for strategy/ modules."""
import pytest
import asyncio
import numpy as np
import pandas as pd

from common.types import Side, SignalAction, VolumeProfile
from strategy.neutral_grid_strategy import NeutralGridStrategy
from strategy.trend_dca_strategy import TrendDcaStrategy
from strategy.strategy_router import StrategyRouter
from indicators.technical_indicators import add_standard_indicators


def _run(coro):
    """Helper to run async coroutines in tests."""
    return asyncio.get_event_loop().run_until_complete(coro)


class TestNeutralGridStrategy:
    def test_generate_grid_levels_count(self, config, volume_profile):
        config.GRID_LEVELS = 6
        strategy = NeutralGridStrategy(config)
        levels = strategy.generate_grid_levels("BTC/USDT", volume_profile, 4000.0)
        # 6 levels: 3 buy + 3 sell
        assert len(levels) == 6

    def test_buy_levels_below_poc(self, config, volume_profile):
        strategy = NeutralGridStrategy(config)
        levels = strategy.generate_grid_levels("BTC/USDT", volume_profile, 4000.0)
        for level in levels:
            if level.side == "buy":
                assert level.price <= volume_profile.poc

    def test_sell_levels_above_poc(self, config, volume_profile):
        strategy = NeutralGridStrategy(config)
        levels = strategy.generate_grid_levels("BTC/USDT", volume_profile, 4000.0)
        for level in levels:
            if level.side == "sell":
                assert level.price >= volume_profile.poc

    def test_on_market_state_emits_grid_signals(self, config, volume_profile):
        strategy = NeutralGridStrategy(config)
        market_state = {
            "price": volume_profile.poc,
            "volume_profile": volume_profile,
            "position": None,
            "equity": 10000.0,
        }
        signals = _run(strategy.on_market_state("BTC/USDT", market_state))
        # First call should build grid
        assert len(signals) > 0
        assert all(s.action == SignalAction.GRID_PLACE for s in signals)


class TestTrendDcaStrategy:
    def _make_trend_df(self, direction="up", n=300):
        """Create a DataFrame that should trigger a trend signal."""
        np.random.seed(42)
        if direction == "up":
            price = np.linspace(50000, 80000, n) + np.random.normal(0, 100, n)
        else:
            price = np.linspace(80000, 50000, n) + np.random.normal(0, 100, n)
        df = pd.DataFrame({
            "open": price * 0.999,
            "high": price * 1.003,
            "low": price * 0.997,
            "close": price,
            "volume": np.random.uniform(100, 500, n),
        })
        return add_standard_indicators(df)

    def test_generate_trend_signal_long(self, config):
        strategy = TrendDcaStrategy(config)
        df = self._make_trend_df("up")
        result = strategy.generate_trend_signal("BTC/USDT", df)
        assert result == Side.LONG

    def test_generate_trend_signal_short(self, config):
        strategy = TrendDcaStrategy(config)
        df = self._make_trend_df("down")
        result = strategy.generate_trend_signal("BTC/USDT", df)
        assert result == Side.SHORT

    def test_generate_trend_signal_none_on_empty(self, config):
        strategy = TrendDcaStrategy(config)
        result = strategy.generate_trend_signal("BTC/USDT", None)
        assert result is None

    def test_plan_dca_levels(self, config):
        config.DCA_STEPS = 3
        strategy = TrendDcaStrategy(config)
        levels = strategy.plan_dca_levels(60000.0, Side.LONG, 1000.0)
        assert len(levels) == 3
        # Each DCA level should be below entry for LONG
        for level in levels:
            assert level.price < 60000.0

    def test_plan_dca_levels_short(self, config):
        config.DCA_STEPS = 3
        strategy = TrendDcaStrategy(config)
        levels = strategy.plan_dca_levels(60000.0, Side.SHORT, 1000.0)
        # Each DCA level should be above entry for SHORT
        for level in levels:
            assert level.price > 60000.0

    def test_sl_tp_calculation(self, config):
        strategy = TrendDcaStrategy(config)
        sl, tp = strategy.calculate_sl_tp(60000.0, Side.LONG, 1000.0)
        assert sl < 60000.0  # SL below entry for long
        assert tp > 60000.0  # TP above entry for long

    def test_sl_tp_short(self, config):
        strategy = TrendDcaStrategy(config)
        sl, tp = strategy.calculate_sl_tp(60000.0, Side.SHORT, 1000.0)
        assert sl > 60000.0  # SL above entry for short
        assert tp < 60000.0  # TP below entry for short

    def test_exit_on_tp_with_none_sl(self, config):
        """Positions with None SL/TP should not crash."""
        strategy = TrendDcaStrategy(config)
        market_state = {
            "df": self._make_trend_df("up"),
            "position": {
                "is_active": True,
                "side": "LONG",
                "stop_loss": None,
                "take_profit": None,
                "dca_levels": [],
            },
            "equity": 10000.0,
        }
        # Should not raise TypeError
        signals = _run(strategy.on_new_candle("BTC/USDT", market_state))
        assert isinstance(signals, list)


class TestStrategyRouter:
    def test_routes_to_grid_in_range(self, config, volume_profile):
        grid = NeutralGridStrategy(config)
        trend = TrendDcaStrategy(config)
        router = StrategyRouter(grid, trend)

        market_state = {
            "price": volume_profile.poc,
            "volume_profile": volume_profile,
            "position": None,
            "equity": 10000.0,
        }
        signals = _run(router.route_signals("BTC/USDT", "range", market_state))
        # Should get grid signals
        assert any(s.action == SignalAction.GRID_PLACE for s in signals)

    def test_routes_to_trend_in_trend(self, config):
        np.random.seed(42)
        grid = NeutralGridStrategy(config)
        trend = TrendDcaStrategy(config)
        router = StrategyRouter(grid, trend)

        n = 300
        price = np.linspace(50000, 80000, n) + np.random.normal(0, 100, n)
        df = pd.DataFrame({
            "open": price * 0.999,
            "high": price * 1.003,
            "low": price * 0.997,
            "close": price,
            "volume": np.random.uniform(100, 500, n),
        })
        df = add_standard_indicators(df)

        market_state = {
            "df": df,
            "position": None,
            "equity": 10000.0,
        }
        # Should not produce grid signals in trend mode
        signals = _run(router.route_signals("BTC/USDT", "trend", market_state))
        assert not any(s.action == SignalAction.GRID_PLACE for s in signals)
