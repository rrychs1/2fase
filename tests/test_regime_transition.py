import pytest
import asyncio
import sys
import os
import logging
from unittest.mock import MagicMock, AsyncMock

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from orchestration.bot_runner import BotRunner
from strategy.neutral_grid_strategy import NeutralGridStrategy
from strategy.trend_dca_strategy import TrendDcaStrategy

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("TransitionTest")

@pytest.mark.anyio
async def test_regime_transition():
    logger.info("Starting Regime Transition Verification...")
    
    config = MagicMock()
    config.SYMBOLS = ["BTC/USDT"]
    config.ANALYSIS_ONLY = False
    
    from config.config_loader import Config
    config = Config()
    config.SYMBOLS = ["BTC/USDT"]
    config.ANALYSIS_ONLY = False
    config.POLLING_INTERVAL = 1
    
    runner = BotRunner(config=config)
    runner.risk_manager.check_daily_drawdown = MagicMock(return_value=False)
    runner.risk_manager.sync_reference_equity = MagicMock(return_value=(False, 0.0))
    runner.risk_manager.is_kill_switch_active = False
    runner.risk_manager.day_start_equity = 0.0
    runner.risk_manager.reference_equity = 10000.0
    runner.regime_detector = MagicMock()
    runner.neutral_grid = MagicMock(spec=NeutralGridStrategy)
    runner.trend_dca = MagicMock(spec=TrendDcaStrategy)
    from strategy.strategy_router import StrategyRouter
    runner.router = MagicMock(spec=StrategyRouter)
    runner.router.route_signals = AsyncMock(return_value=[])
    
    # Mock Execution
    runner.execution = MagicMock()
    runner.execution.get_account_pnl = AsyncMock(return_value=0.0)
    runner.execution.get_position = AsyncMock(return_value=None)
    runner.execution.close_all_positions = AsyncMock()
    runner.execution.place_order = AsyncMock(return_value={'id': 'test_order'})
    runner.execution.cancel_order = AsyncMock(return_value=True)
    
    # Mock Telegram (Phase 26)
    runner.telegram = MagicMock()
    runner.telegram.info = AsyncMock()
    runner.telegram.warning = AsyncMock()
    runner.telegram.error = AsyncMock()
    runner.telegram.critical = AsyncMock()
    runner.telegram.trade = AsyncMock()
    
    # Mock Exchange to avoid real calls
    import pandas as pd
    dummy_ohlcv = [[123456789, 60000, 61000, 59000, 60000, 100]] * 50
    runner.exchange = MagicMock()
    runner.exchange.fetch_ohlcv = AsyncMock(return_value=dummy_ohlcv)
    runner.exchange.fetch_open_orders = AsyncMock(return_value=[])
    runner.exchange.fetch_my_trades = AsyncMock(return_value=[])
    runner.exchange.fetch_positions = AsyncMock(return_value=[])
    runner.exchange.fetch_balance = AsyncMock(return_value={'total': {'USDT': 10000}})
    runner.exchange._apply_backoff = AsyncMock()
    
    # Mock Status/Dashboard to avoid JSON issues with MagicMocks
    runner.update_status = MagicMock()
    runner._write_dashboard_state = MagicMock()
    
    # 1. State: RANGE
    runner.regime_detector.detect_regime.return_value = "range"
    runner.router.route_signals.return_value = []
    
    logger.info("Current Regime: RANGE")
    await runner.iterate()
    
    from unittest.mock import ANY
    # Verify router was called with 'range'
    runner.router.route_signals.assert_called_with("BTC/USDT", "range", ANY)
    logger.info("Success: Router called with range regime.")
    
    # 2. State Change: TREND
    runner.regime_detector.detect_regime.return_value = "trend"
    runner.router.route_signals.reset_mock()
    runner.router.route_signals.return_value = []
    
    logger.info("Switching Regime to: TREND")
    await runner.iterate()
    
    # Verify router was called with 'trend'
    runner.router.route_signals.assert_called_with("BTC/USDT", "trend", ANY)
    logger.info("Success: Router called with trend regime.")

    logger.info("Regime Transition Verification Complete!")

if __name__ == "__main__":
    asyncio.run(test_regime_transition())
