import pytest
import pandas as pd
import numpy as np
import time
from unittest.mock import MagicMock, patch, AsyncMock
from common.types import Side, SignalAction, Signal, VolumeProfile, GridLevel, GridState
from strategy.neutral_grid_strategy import NeutralGridStrategy
from strategy.trend_dca_strategy import TrendDcaStrategy
from strategy.strategy_router import StrategyRouter

@pytest.fixture
def mock_config():
    config = MagicMock()
    config.GRID_ATR_MULTIPLIER = 1.0
    config.GRID_MAX_LEVELS = 10
    config.DCA_STEPS = 3
    return config

@pytest.fixture
def grid_strategy(mock_config):
    return NeutralGridStrategy(mock_config)

@pytest.fixture
def trend_strategy(mock_config):
    return TrendDcaStrategy(mock_config)

# ─────────────────────────────────────────────────────────────────────────────
# Neutral Grid Strategy Tests
# ─────────────────────────────────────────────────────────────────────────────

def test_grid_level_generation_volatility_scaling(grid_strategy):
    vp = VolumeProfile(poc=100.0, vah=110.0, val=90.0)
    market_state = {'price': 100.0, 'atr': 0.5, 'volatility_regime': 'MEDIUM'}
    
    # max_distance = 100 * 0.025 = 2.5
    # MEDIUM: spacing = 1.0 * 0.5 = 0.5
    # Buy: 100-0.5, 100-1.0, 100-1.5, 100-2.0, 100-2.5 (5 levels)
    # Sell: 100+0.5, 100+1.0, 100+1.5, 100+2.0, 100+2.5 (5 levels)
    levels = grid_strategy.generate_grid_levels("BTC/USDT", vp, 1000.0, market_state)
    assert len(levels) == 10
    assert levels[0].price == 97.5  # Lowest buy
    assert levels[-1].price == 102.5 # Highest sell

    # HIGH: spacing = 1.5 * 2.0 = 3.0
    market_state['volatility_regime'] = 'HIGH'
    levels_high = grid_strategy.generate_grid_levels("BTC/USDT", vp, 1000.0, market_state)
    # 10/3 = 3 levels each side
    assert len(levels_high) == 6

@pytest.mark.asyncio
async def test_grid_initial_placement(grid_strategy):
    vp = VolumeProfile(poc=100.0, vah=110.0, val=90.0)
    market_state = {
        'price': 100.0,
        'volume_profile': vp,
        'atr': 5.0,
        'volatility_regime': 'MEDIUM',
        'equity': 1000.0
    }
    
    # mock time to avoid rebuild issues
    with patch('time.time', return_value=1000.0):
        signals = await grid_strategy.on_market_state("BTC/USDT", market_state)
        assert len(signals) > 0
        assert signals[0].action == SignalAction.GRID_PLACE
        assert signals[0].strategy == "GridInitial"

@pytest.mark.asyncio
async def test_grid_rebuild_after_cooldown(grid_strategy):
    vp = VolumeProfile(poc=100.0, vah=110.0, val=90.0)
    market_state = {
        'price': 120.0, # Outside VA
        'volume_profile': vp,
        'atr': 2.0,
        'volatility_regime': 'MEDIUM',
        'equity': 1000.0
    }
    
    # 1. Initial placement
    with patch('time.time', return_value=1000.0):
        await grid_strategy.on_market_state("BTC/USDT", market_state)
        
    # 2. Price stays outside for 3 checks
    with patch('time.time', return_value=1001.0):
        await grid_strategy.on_market_state("BTC/USDT", market_state) # outside (1)
        await grid_strategy.on_market_state("BTC/USDT", market_state) # outside (2)
        
    # 3. Third check, 10 mins passed
    with patch('time.time', return_value=1700.0):
        signals = await grid_strategy.on_market_state("BTC/USDT", market_state) # outside (3) + cooldown ok
        assert len(signals) > 0
        assert any(s.strategy == "GridInitial" for s in signals)

# ─────────────────────────────────────────────────────────────────────────────
# Trend DCA Strategy Tests
# ─────────────────────────────────────────────────────────────────────────────

def test_trend_detection_logic(trend_strategy):
    # Bullish data (needs >= 20 rows)
    df_bull = pd.DataFrame({
        'EMA_fast': [10]*20,
        'EMA_slow': [8]*20,
        'MACD': [0.1]*20,
        'close': [100]*20
    })
    # Update last row to ensure it's bullish
    df_bull.at[19, 'EMA_fast'] = 12
    df_bull.at[19, 'EMA_slow'] = 10
    df_bull.at[19, 'MACD'] = 0.3
    df_bull.at[19, 'close'] = 102
    
    assert trend_strategy.generate_trend_signal("BTC/USDT", df_bull) == Side.LONG
    
    # Bearish data
    df_bear = pd.DataFrame({
        'EMA_fast': [10]*20,
        'EMA_slow': [12]*20,
        'MACD': [-0.1]*20,
        'close': [100]*20
    })
    df_bear.at[19, 'EMA_fast'] = 8
    df_bear.at[19, 'EMA_slow'] = 10
    df_bear.at[19, 'MACD'] = -0.3
    df_bear.at[19, 'close'] = 98
    
    assert trend_strategy.generate_trend_signal("BTC/USDT", df_bear) == Side.SHORT

@pytest.mark.asyncio
async def test_trend_pullback_entry(trend_strategy):
    # Setup Bullish trend with a pullback
    # Needs >= 20 rows
    data = {
        'EMA_fast': [100.0] * 20,
        'EMA_slow': [90.0] * 20,
        'MACD': [1.0] * 20,
        'close': [105.0] * 20,
        'low': [102.0] * 20,
        'high': [106.0] * 20,
        'ATR': [5.0] * 20
    }
    df = pd.DataFrame(data)
    
    # Pullback: prev_low <= EMA_fast and last_close > EMA_fast
    df.at[18, 'low'] = 98.0  # prev_low (98) <= EMA_fast (100)
    df.at[19, 'close'] = 102.0 # last_close (102) > EMA_fast (100)
    
    market_state = {
        'df': df,
        'price': 102.0,
        'equity': 1000.0,
        'position': {'is_active': False}
    }
    
    signals = await trend_strategy.on_new_candle("BTC/USDT", market_state)
    assert len(signals) == 1
    assert signals[0].action == SignalAction.ENTER_LONG
    assert signals[0].price == 102.0

@pytest.mark.asyncio
async def test_trend_dca_replenishment(trend_strategy):
    # Setup active position
    trend_strategy.active_positions["BTC/USDT"] = MagicMock(
        is_active=True,
        dca_levels=[MagicMock(price=90.0, amount=1.0, filled=False)]
    )
    
    data = {
        'close': [100.0] * 20,
        'EMA_fast': [110.0] * 20,
        'EMA_slow': [100.0] * 20,
        'MACD': [1.0] * 20,
        'ATR': [5.0] * 20
    }
    df = pd.DataFrame(data)
    df.at[19, 'close'] = 89.0 # Price dropped to 89 (below DCA 90)
    
    market_state = {
        'df': df,
        'position': {'is_active': True, 'side': 'LONG', 'take_profit': 150.0},
        'equity': 1000.0
    }
    
    signals = await trend_strategy.on_new_candle("BTC/USDT", market_state)
    assert any(s.action == SignalAction.DCA_ADD for s in signals)

# ─────────────────────────────────────────────────────────────────────────────
# Strategy Router Tests
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_router_delegation(grid_strategy, trend_strategy):
    router = StrategyRouter(grid_strategy, trend_strategy)
    
    # 1. Range regime
    grid_strategy.on_market_state = AsyncMock(return_value=[Signal("BTC", SignalAction.HOLD)])
    signals = await router.route_signals("BTC/USDT", "range", {})
    grid_strategy.on_market_state.assert_called_once()
    assert signals[0].action == SignalAction.HOLD
    
    # 2. Trend regime
    trend_strategy.on_new_candle = AsyncMock(return_value=[Signal("BTC", SignalAction.ENTER_LONG)])
    signals = await router.route_signals("BTC/USDT", "trend", {})
    trend_strategy.on_new_candle.assert_called_once()
    assert signals[0].action == SignalAction.ENTER_LONG
