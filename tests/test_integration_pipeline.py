import pytest
import asyncio
import pandas as pd
import numpy as np
from unittest.mock import AsyncMock, MagicMock, patch
from common.types import Side, SignalAction, Signal, Regime
from config.config_loader import Config
from orchestration.bot_runner import BotRunner

@pytest.fixture
def mock_dependencies():
    with patch('orchestration.bot_runner.setup_logger'), \
         patch('data.db_manager.DbManager'), \
         patch('data.websocket_manager.WebsocketManager'), \
         patch('logging_monitoring.telegram_alert_service.TelegramAlertService'), \
         patch('orchestration.bot_runner.write_bot_state'), \
         patch('orchestration.bot_runner.add_standard_indicators', side_effect=lambda x: x), \
         patch('orchestration.bot_runner.compute_volume_profile', return_value=MagicMock()), \
         patch('logging_monitoring.metrics_server.bot_unrealized_pnl'), \
         patch('logging_monitoring.metrics_server.bot_daily_drawdown_pct'), \
         patch('logging_monitoring.metrics_server.bot_current_exposure'), \
         patch('logging_monitoring.metrics_server.bot_system_health'), \
         patch('logging_monitoring.metrics_server.bot_ws_connected'), \
         patch('execution.shadow_executor.json.dump'), \
         patch('execution.shadow_executor.open', create=True):
        yield

@pytest.fixture
def bot_config():
    config = Config()
    config.EXECUTION_MODE = 'SHADOW'
    config.SYMBOLS = ['BTC/USDT']
    config.TF_GRID = '4h'
    config.TF_TREND = '1h'
    config.CANDLES_ANALYSIS_LIMIT = 50
    config.DCA_STEPS = 3
    config.GRID_ATR_MULTIPLIER = 1.0
    config.ANALYSIS_ONLY = False # Enable execution
    return config

@pytest.fixture
def mock_exchange():
    exchange = MagicMock()
    exchange.init = AsyncMock()
    exchange.close = AsyncMock()
    exchange.fetch_balance = AsyncMock(return_value={'total': {'USDT': 10000.0}})
    exchange.fetch_open_orders = AsyncMock(return_value=[])
    exchange.fetch_my_trades = AsyncMock(return_value=[])
    exchange.fetch_order_book = AsyncMock(return_value={
        'bids': [[99.9, 10.0]],
        'asks': [[100.1, 10.0]]
    })
    exchange.validate_order_filters = MagicMock(return_value=(True, "OK"))
    exchange.config = MagicMock()
    exchange.config.MAX_SPREAD_PCT = 0.01
    exchange.config.LIQUIDITY_HAIRCUT = 0.1
    exchange.config.MAX_ORDER_DEPTH_RATIO = 0.5
    exchange.config.MAX_SLIPPAGE_PCT = 0.005
    return exchange

def generate_bullish_pullback_data(price_start=100.0, length=50):
    """
    Generates a DataFrame that satisfies:
    1. Bullish Trend (EMA_fast > EMA_slow, MACD > 0)
    2. Pullback (prev_low <= EMA_fast AND last_close > EMA_fast)
    """
    df = pd.DataFrame({
        'timestamp': pd.date_range(start='2023-01-01', periods=length, freq='h'),
        'open': np.linspace(price_start, price_start + 10, length),
        'high': np.linspace(price_start + 1, price_start + 11, length),
        'low': np.linspace(price_start - 1, price_start + 9, length),
        'close': np.linspace(price_start, price_start + 10, length),
        'volume': [100.0] * length
    })
    
    # Add indicators manually to ensure detection
    df['EMA_fast'] = np.linspace(price_start, price_start + 10, length)
    df['EMA_slow'] = np.linspace(price_start - 5, price_start + 5, length)
    df['MACD'] = 1.0 # Constant bullish momentum
    df['ATR'] = 2.0  # Constant volatility
    
    # Setup Pullback in the last two rows
    # Logic: prev_low (length-2) <= EMA_fast (length-1) AND last_close (length-1) > EMA_fast (length-1)
    # EMA_fast_last = price_start + 10
    ema_fast_last = df.iloc[-1]['EMA_fast']
    df.at[length-2, 'low'] = ema_fast_last - 1.0 # Pullback touched/went below EMA_fast
    df.at[length-1, 'close'] = ema_fast_last + 0.5 # bounced above
    
    return df

@pytest.mark.asyncio
async def test_full_pipeline_shadow_execution(mock_dependencies, bot_config, mock_exchange):
    # 1. Initialize BotRunner
    runner = BotRunner(config=bot_config, exchange=mock_exchange)
    
    # Force SHADOW mode manually if config didn't propagate correctly in Mock init
    runner.execution_router.mode = 'SHADOW'
    runner.execution_router.shadow_executor.state['balance'] = 10000.0
    runner.execution_router.shadow_executor.state['positions'] = {}
    
    # 2. Setup Data
    df_trend = generate_bullish_pullback_data(100.0, 50)
    df_grid = generate_bullish_pullback_data(100.0, 50) # Same for simplicity
    
    # Inject into data engine cache
    runner.data_engine.data[('BTC/USDT', '1h')] = df_trend
    runner.data_engine.data[('BTC/USDT', '4h')] = df_grid
    
    # 3. Simulate specific market condition: Trend Regime
    # We force the regime detector to return 'trend' to trigger TrendDcaStrategy
    with patch.object(runner.regime_detector, 'detect_regime', return_value='trend'):
        # 4. Run Iteration
        await runner.iterate(target_symbol='BTC/USDT')
    
    # 5. Verifications
    
    # Verify iteration count
    assert runner.iteration_count == 1
    
    # Verify Shadow Executor opened a position
    shadow_state = runner.execution_router.shadow_executor.state
    assert 'BTC/USDT' in shadow_state['positions']
    pos = shadow_state['positions']['BTC/USDT']
    assert pos['side'] == 'LONG'
    assert pos['amount'] > 0
    
    # Verify Signal was processed
    assert runner.metrics['signals_processed'] >= 1
    assert runner.metrics['orders_placed'] >= 1
    
    # 6. Simulate another iteration to verify PnL and Balance (no closure yet)
    # Move price up
    new_price = 115.0
    df_trend.iloc[-1, df_trend.columns.get_loc('close')] = new_price
    
    await runner.iterate(target_symbol='BTC/USDT')
    
    # Verify equity increased due to unrealized PnL
    equity, pnl = await runner.execution_router.get_equity_and_pnl({'BTC/USDT': new_price})
    assert pnl > 0
    assert equity > 10000.0
    
    # 7. Simulate Exit
    # Force strategy to return EXIT_LONG signal (mocking strategy_router)
    exit_signal = Signal(symbol='BTC/USDT', action=SignalAction.EXIT_LONG, side=Side.LONG, price=new_price, amount=pos['amount'])
    with patch.object(runner.strategy_router, 'route_signals', AsyncMock(return_value=[exit_signal])):
        await runner.iterate(target_symbol='BTC/USDT')
        
    # Verify position is closed and balance updated
    assert 'BTC/USDT' not in shadow_state['positions']
    assert shadow_state['balance'] > 10000.0
    assert len(shadow_state['history']) == 1
