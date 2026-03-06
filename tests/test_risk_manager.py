"""Tests for risk/risk_manager.py."""
import pytest
from risk.risk_manager import RiskManager
from datetime import date


class TestPositionSizing:
    def test_basic_formula(self, config):
        """size = (equity * risk%) / |entry - SL|"""
        rm = RiskManager(config)
        rm.is_kill_switch_active = False # Reset state
        rm.sync_reference_equity(10000.0, 0.0)
        # equity=10000, risk=1%, entry=60000, sl=58000
        # -> risk_amount = 100, price_risk = 2000 -> size = 0.05
        size = rm.calculate_position_size("BTC/USDT", 60000.0, 58000.0)
        assert abs(size - 0.05) < 1e-6

    def test_leverage_cap(self, config):
        """Position notional should not exceed equity * leverage."""
        config.LEVERAGE = 3
        config.MAX_RISK_PER_TRADE = 0.5  # Very high risk -> would exceed leverage
        rm = RiskManager(config)
        rm.is_kill_switch_active = False
        rm.sync_reference_equity(10000.0, 0.0)
        size = rm.calculate_position_size("BTC/USDT", 60000.0, 59000.0)
        max_notional = 10000 * 3
        assert (size * 60000.0) <= max_notional + 0.01

    def test_no_stop_loss_fallback(self, config):
        """When SL is None, use fallback formula."""
        rm = RiskManager(config)
        rm.is_kill_switch_active = False
        rm.sync_reference_equity(10000.0, 0.0)
        size = rm.calculate_position_size("BTC/USDT", 60000.0, None)
        # Fallback: (equity * risk%) / entry = (10000 * 0.01) / 60000
        expected = (10000 * 0.01) / 60000
        assert abs(size - expected) < 1e-8

    def test_same_entry_and_sl_fallback(self, config):
        """When entry == SL, use fallback."""
        rm = RiskManager(config)
        rm.is_kill_switch_active = False
        rm.sync_reference_equity(10000.0, 0.0)
        size = rm.calculate_position_size("BTC/USDT", 60000.0, 60000.0)
        expected = (10000 * 0.01) / 60000
        assert abs(size - expected) < 1e-8

    def test_short_position_sizing(self, config):
        """SL above entry for shorts should still work."""
        rm = RiskManager(config)
        rm.is_kill_switch_active = False
        rm.sync_reference_equity(10000.0, 0.0)
        # entry=60000, sl=62000 (short) -> price_risk=2000
        size = rm.calculate_position_size("BTC/USDT", 60000.0, 62000.0)
        assert abs(size - 0.05) < 1e-6


class TestDailyDrawdown:
    def test_under_limit(self, config):
        config.DAILY_LOSS_LIMIT = 0.02
        rm = RiskManager(config)
        rm.is_kill_switch_active = False # Manual reset for test
        rm.day_start_equity = 0.0 # Force re-init from current equity
        # -100 on 10000 equity = -1% < 2% limit
        assert rm.check_daily_drawdown(-100, 10000) == False

    def test_at_limit(self, config):
        config.DAILY_LOSS_LIMIT = 0.02
        rm = RiskManager(config)
        rm.is_kill_switch_active = False
        # -200 on 10000 equity = -2% = exactly at limit
        assert rm.check_daily_drawdown(-200, 10000) == True

    def test_over_limit_triggers_kill_switch(self, config):
        config.DAILY_LOSS_LIMIT = 0.02
        rm = RiskManager(config)
        rm.is_kill_switch_active = False
        # -500 on 10000 equity = -5% > 2% limit
        assert rm.check_daily_drawdown(-500, 10000) == True

    def test_positive_pnl_safe(self, config):
        rm = RiskManager(config)
        rm.is_kill_switch_active = False
        assert rm.check_daily_drawdown(500, 10000) == False
