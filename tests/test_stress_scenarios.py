import pytest
import asyncio
import pandas as pd
import numpy as np
import time
import os
import json
from unittest.mock import AsyncMock, MagicMock, patch
from common.types import Side, SignalAction, Signal
from config.config_loader import Config
from orchestration.bot_runner import BotRunner

@pytest.fixture
def stress_config():
    config = Config()
    config.EXECUTION_MODE = 'SHADOW'
    config.SYMBOLS = ['BTC/USDT']
    config.KILL_SWITCH_ENABLED = True
    config.DAILY_LOSS_LIMIT = 0.001 # 0.1% for easier triggering
    config.ANALYSIS_ONLY = False
    config.TF_GRID = '1h'
    config.TF_TREND = '1h'
    config.LEVERAGE = 10
    config.CANDLES_ANALYSIS_LIMIT = 50
    config.MAX_SPREAD_PCT = 0.05 # 5% for stress
    config.MAX_SLIPPAGE_PCT = 0.05
    return config

@pytest.fixture
def mock_deps():
    # Cleanup shadow files before each test to ensure clean state
    for f in ["data/virtual_account_shadow.json", "data/shadow_trades.jsonl", "risk_state.json", ".kill_switch_lock"]:
        if os.path.exists(f): os.remove(f)
    
    # Provide a dummy volume profile with numeric values
    dummy_vp = MagicMock()
    dummy_vp.val = 98.0
    dummy_vp.vah = 102.0
    dummy_vp.poc = 100.0

    with patch('orchestration.bot_runner.setup_logger'), \
         patch('data.db_manager.DbManager'), \
         patch('data.websocket_manager.WebsocketManager'), \
         patch('logging_monitoring.telegram_alert_service.TelegramAlertService'), \
         patch('orchestration.bot_runner.write_bot_state'), \
         patch('orchestration.bot_runner.add_standard_indicators', side_effect=lambda x: x), \
         patch('orchestration.bot_runner.compute_volume_profile', return_value=dummy_vp), \
         patch('monitoring.metrics.bot_unrealized_pnl'), \
         patch('monitoring.metrics.bot_daily_drawdown_pct'), \
         patch('monitoring.metrics.bot_current_exposure'), \
         patch('monitoring.metrics.bot_system_health'), \
         patch('monitoring.metrics.bot_ws_connected'), \
         patch('execution.shadow_executor.json.dump'), \
         patch('execution.shadow_executor.open', create=True):
        yield

@pytest.mark.asyncio
async def test_flash_crash_resilience(mock_deps, stress_config):
    """
    Simulate a -25% price gap and verify kill switch enforcement.
    """
    mock_exchange = MagicMock()
    mock_exchange.init = AsyncMock()
    mock_exchange.close = AsyncMock()
    mock_exchange.fetch_balance = AsyncMock(return_value={'total': {'USDT': 10000.0}, 'free': {'USDT': 10000.0}})
    mock_exchange.fetch_open_orders = AsyncMock(return_value=[])
    mock_exchange.fetch_my_trades = AsyncMock(return_value=[])
    mock_exchange.fetch_order_book = AsyncMock(return_value={'bids': [[100, 1000]], 'asks': [[100.1, 1000]]})
    mock_exchange.validate_order_filters = MagicMock(return_value=(True, "OK"))
    
    ohlcv_normal = [[int((time.time() - (100-i)*3600)*1000), 100, 101, 99, 100, 1000] for i in range(100)]
    ohlcv_crash = [[int((time.time() - (100-i)*3600)*1000), 100, 101, 70, 75, 1000] for i in range(100)]
    
    mock_exchange.fetch_ohlcv = AsyncMock(side_effect=[ohlcv_normal, ohlcv_crash, ohlcv_crash, ohlcv_crash])
    
    runner = BotRunner(config=stress_config, exchange=mock_exchange)
    runner.execution_router.shadow_executor.state['balance'] = 10000.0


    # 1. Open Position
    buy_signal = Signal(symbol='BTC/USDT', action=SignalAction.ENTER_LONG, side=Side.LONG, price=100.0, amount=1.0)
    with patch.object(runner.strategy_router, 'route_signals', AsyncMock(return_value=[buy_signal])):
        await runner.iterate(target_symbol='BTC/USDT')
    
    assert 'BTC/USDT' in runner.execution_router.shadow_executor.state['positions']
    
    # 2. Crash
    # Clear cache to force a new fetch_ohlcv call which will return ohlcv_crash
    runner.data_engine.data = {}
    
    await runner.iterate(target_symbol='BTC/USDT')
    assert runner.risk_manager.is_kill_switch_active == True

@pytest.mark.asyncio
async def test_high_frequency_load_stress(mock_deps, stress_config):
    """
    Simulate multiple signals to verify stability.
    """
    mock_exchange = MagicMock()
    mock_exchange.init = AsyncMock()
    mock_exchange.fetch_balance = AsyncMock(return_value={'total': {'USDT': 1000000.0}, 'free': {'USDT': 1000000.0}})
    mock_exchange.fetch_open_orders = AsyncMock(return_value=[])
    mock_exchange.fetch_my_trades = AsyncMock(return_value=[])
    mock_exchange.fetch_order_book = AsyncMock(return_value={'bids': [[100, 5000]], 'asks': [[101, 5000]]})
    mock_exchange.validate_order_filters = MagicMock(return_value=(True, "OK"))
    
    ohlcv = [[int(time.time()*1000) - i*3600000, 100, 101, 99, 100, 1000] for i in range(100)]
    mock_exchange.fetch_ohlcv = AsyncMock(return_value=ohlcv)
    
    runner = BotRunner(config=stress_config, exchange=mock_exchange)
    
    # Multiple different small signals to fill the "positions" limit in shadow executor if needed
    # (Actually ShadowExecutor only allows 1 position per symbol, so we can only ENTER once per iterate if not closed)
    signals = [
        Signal(symbol='BTC/USDT', action=SignalAction.ENTER_LONG, side=Side.LONG, price=100.0, amount=0.001)
    ]
    
    with patch.object(runner.strategy_router, 'route_signals', AsyncMock(return_value=signals)):
        for i in range(10): 
            await runner.iterate(target_symbol='BTC/USDT')
            # Close it so next iter can open it again
            runner.execution_router.shadow_executor.state['positions'] = {}
            
    assert runner.iteration_count == 10
    assert runner.metrics['signals_processed'] == 10

@pytest.mark.asyncio
async def test_network_and_api_failure_graceful_handling(mock_deps, stress_config):
    """
    Verify that the bot handles API failures gracefully without crashing.
    """
    mock_exchange = MagicMock()
    mock_exchange.init = AsyncMock()
    mock_exchange.fetch_balance = AsyncMock(return_value={'total': {'USDT': 10000.0}, 'free': {'USDT': 10000.0}})
    mock_exchange.fetch_open_orders = AsyncMock(return_value=[])
    mock_exchange.fetch_my_trades = AsyncMock(return_value=[])
    mock_exchange.fetch_order_book = AsyncMock(return_value={'bids': [[100, 10]], 'asks': [[101, 10]]})
    mock_exchange.validate_order_filters = MagicMock(return_value=(True, "OK"))
    
    # Mock DataEngine failure (caught and retried)
    mock_exchange.fetch_ohlcv = AsyncMock(side_effect=[Exception("API Error")] * 10) 
    
    runner = BotRunner(config=stress_config, exchange=mock_exchange)
    
    # Use small sleep to speed up retries in DataEngine
    with patch('asyncio.sleep', AsyncMock()):
        await runner.iterate(target_symbol='BTC/USDT')
        
    # Should have finished the iteration (potentially without routing due to data error)
    assert runner.iteration_count == 1
    # Check if data fetch was attempted
    assert mock_exchange.fetch_ohlcv.call_count >= 3
