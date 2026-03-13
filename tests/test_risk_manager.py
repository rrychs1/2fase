import pytest
import os
import json
import time
from datetime import date, datetime
from unittest.mock import MagicMock, patch
from risk.risk_manager import RiskManager
from common.types import Signal, SignalAction, Side

@pytest.fixture
def rm(config, tmp_path):
    # Patch the state and lock files to use a temp directory
    state_file = str(tmp_path / "risk_state.json")
    lock_file = str(tmp_path / ".kill_switch_lock")
    
    with patch.object(RiskManager, 'DEFAULT_STATE_FILE', state_file), \
         patch.object(RiskManager, 'DEFAULT_LOCK_FILE', lock_file):
        manager = RiskManager(config)
        # Ensure we start fresh
        manager.is_kill_switch_active = False
        manager.daily_pnl = 0.0
        manager.day_start_equity = 0.0
        yield manager

class TestPositionSizing:
    def test_risk_per_trade_limit(self, rm):
        """size = (equity * risk%) / |entry - SL|"""
        rm.sync_reference_equity(10000.0, 0.0)
        # 1% risk of 10k is 100. Price risk is 60k-58k = 2k. Size = 100/2000 = 0.05
        size = rm.calculate_position_size("BTC/USDT", 60000.0, 58000.0)
        assert abs(size - 0.05) < 1e-6

    def test_leverage_cap_enforced(self, rm, config):
        config.LEVERAGE = 2
        rm.sync_reference_equity(10000.0, 0.0)
        # 1% risk, but very tight stop (100). Size would be 1.0 (60k notional).
        # Max notional is 10k * 2 = 20k. Size should be 20k/60k = 0.3333
        size = rm.calculate_position_size("BTC/USDT", 60000.0, 59900.0)
        assert abs(size - 0.333333) < 0.0001
        assert (size * 60000.0) <= 20000.01

    def test_invalid_price_types_hardening(self, rm):
        """Lead Developer Hardening: Block trades with non-numeric prices."""
        rm.sync_reference_equity(10000.0, 0.0)
        size = rm.calculate_position_size("BTC/USDT", "60000", 58000.0)
        assert size == 0.0

class TestInventoryAndExposure:
    def test_per_asset_inventory_limit(self, rm, config, signal_long):
        config.MAX_INVENTORY_RATIO = 0.1 # 10%
        rm.sync_reference_equity(10000.0, 0.0)
        
        # Current position for BTC is already at 8% (800 notional)
        current_positions = {
            "BTC/USDT": {"average_price": 60000.0, "amount": 0.013333} # ~800$
        }
        
        # Try to open another 5% (500$)
        signal_long.price = 60000.0
        signal_long.amount = 0.008333 # 500$
        
        # New amount should be reduced to fit the remaining 2% (200$)
        # 200 / 60000 = 0.003333
        reduced_amount = rm.enforce_inventory_limits("BTC/USDT", signal_long, current_positions)
        assert abs(reduced_amount - 0.003333) < 0.00001

    def test_global_exposure_limit(self, rm, config, signal_long):
        config.MAX_TOTAL_EXPOSURE = 0.2 # 20%
        rm.sync_reference_equity(10000.0, 0.0)
        
        # Total exposure is already 18% across other assets
        current_positions = {
            "ETH/USDT": {"average_price": 3000.0, "amount": 0.6} # 1800$
        }
        
        # Try to open 10% of BTC (1000$)
        signal_long.price = 60000.0
        signal_long.amount = 0.016666 # 1000$
        
        # Should be reduced to 2% (200$)
        reduced_amount = rm.enforce_inventory_limits("BTC/USDT", signal_long, current_positions)
        assert abs(reduced_amount - 0.003333) < 0.00001

    def test_blocked_when_at_limit(self, rm, config, signal_long):
        config.MAX_TOTAL_EXPOSURE = 0.1
        rm.sync_reference_equity(10000.0, 0.0)
        current_positions = {"ETH/USDT": {"average_price": 3000.0, "amount": 0.34}} # ~10.2% (> 10%)
        
        amount = rm.enforce_inventory_limits("BTC/USDT", signal_long, current_positions)
        assert amount == 0.0

class TestDailyDrawdownKillSwitch:
    def test_drawdown_triggers_kill_switch(self, rm, config):
        config.DAILY_LOSS_LIMIT = 0.02 # 2%
        rm.sync_reference_equity(10000.0, 0.0)
        
        # Trigger kill switch with 300$ loss (3% > 2%)
        is_blocked = rm.check_daily_drawdown(-300.0, 10000.0)
        assert is_blocked is True
        assert rm.is_kill_switch_active is True
        assert os.path.exists(rm.lock_file)

    def test_kill_switch_blocks_new_trades(self, rm):
        rm.is_kill_switch_active = True
        rm.sync_reference_equity(10000.0, 0.0)
        size = rm.calculate_position_size("BTC/USDT", 60000.0, 58000.0)
        assert size == 0.0

    def test_lock_file_persistence_across_restarts(self, rm, config, tmp_path):
        # Create a lock file manually
        with open(rm.lock_file, 'w') as f:
            f.write(date.today().isoformat())
            
        # Re-init RiskManager
        new_rm = RiskManager(config)
        # We need to manually patch the paths for the new instance as it re-loads
        new_rm.lock_file = rm.lock_file
        new_rm.state_file = rm.state_file
        new_rm.load_state()
        
        assert new_rm.is_kill_switch_active is True

class TestEquityDriftAndEdgeCases:
    def test_high_volatility_drift_safe_mode(self, rm, config):
        config.EQUITY_DRIFT_THRESHOLD = 0.1 # 10%
        rm.sync_reference_equity(10000.0, 0.0)
        
        # Next cycle equity jumps to 12000 (20% jump > 10% threshold)
        drift_alert, val = rm.sync_reference_equity(12000.0, 0.0)
        
        assert drift_alert is True
        assert rm.is_safe_mode is True
        # Blocking calculation in safe mode
        assert rm.calculate_position_size("BTC/USDT", 60000.0, 58000.0) == 0.0

    def test_zero_balance_safeguard(self, rm):
        rm.sync_reference_equity(0.0, 0.0)
        assert rm.is_safe_mode is True
        size = rm.calculate_position_size("BTC/USDT", 60000.0, 58000.0)
        assert size == 0.0

    def test_negative_equity_safeguard(self, rm):
        rm.sync_reference_equity(-500.0, 0.0)
        assert rm.is_safe_mode is True
        size = rm.calculate_position_size("BTC/USDT", 60000.0, 58000.0)
        assert size == 0.0

class TestCooldowns:
    def test_cooldown_blocks_repeated_signals(self, rm):
        rm.sync_reference_equity(10000.0, 0.0)
        rm.trigger_cooldown("BTC/USDT", duration_seconds=10)
        
        size = rm.calculate_position_size("BTC/USDT", 60000.0, 58000.0)
        assert size == 0.0
        
    def test_cooldown_expires(self, rm):
        rm.sync_reference_equity(10000.0, 0.0)
        rm.trigger_cooldown("BTC/USDT", duration_seconds=-1) # Expired
        
        size = rm.calculate_position_size("BTC/USDT", 60000.0, 58000.0)
        assert size > 0
