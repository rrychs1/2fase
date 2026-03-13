import pytest
import pandas as pd
from unittest.mock import AsyncMock, MagicMock
from data.data_engine import DataEngine
from data.websocket_manager import KlineEvent

@pytest.fixture
def mock_exchange():
    exchange = MagicMock()
    exchange.fetch_ohlcv = AsyncMock()
    # Mock config for rolling window limit
    exchange.config = MagicMock()
    exchange.config.CANDLES_ANALYSIS_LIMIT = 5
    return exchange

@pytest.fixture
def data_engine(mock_exchange):
    return DataEngine(mock_exchange)

@pytest.mark.asyncio
async def test_fetch_ohlcv_historical_loading(data_engine, mock_exchange):
    # Mock REST response: [[timestamp, open, high, low, close, volume], ...]
    mock_data = [
        [1600000000000, 50000.0, 50100.0, 49900.0, 50050.0, 1.0],
        [1600000060000, 50050.0, 50200.0, 50000.0, 50150.0, 1.5]
    ]
    mock_exchange.fetch_ohlcv.return_value = mock_data
    
    df = await data_engine.fetch_ohlcv("BTC/USDT", "1m")
    
    assert isinstance(df, pd.DataFrame)
    assert len(df) == 2
    assert "timestamp" in df.columns
    assert df.iloc[0]["close"] == 50050.0
    assert (data_engine.data[("BTC/USDT", "1m")] == df).all().all()

@pytest.mark.asyncio
async def test_update_ohlcv_websocket_append(data_engine, mock_exchange):
    # Set initial historical data
    initial_df = pd.DataFrame([{
        'timestamp': pd.to_datetime(1600000000000, unit='ms'),
        'open': 50000.0, 'high': 50100.0, 'low': 49900.0, 'close': 50050.0, 'volume': 1.0
    }])
    data_engine.data[("BTC/USDT", "1m")] = initial_df
    
    # WebSocket Event
    event = KlineEvent(
        symbol="BTC/USDT",
        timeframe="1m",
        timestamp=1600000060000,
        open=50050.0, high=50200.0, low=50000.0, close=50150.0, volume=1.5,
        is_closed=True
    )
    
    df = await data_engine.update_ohlcv(event)
    
    assert len(df) == 2
    assert df.iloc[-1]["timestamp"] == pd.to_datetime(1600000060000, unit='ms')
    assert df.iloc[-1]["close"] == 50150.0

@pytest.mark.asyncio
async def test_update_ohlcv_deduplication_and_sorting(data_engine):
    # Initial data with 2 candles
    initial_df = pd.DataFrame([
        {'timestamp': pd.to_datetime(1000, unit='ms'), 'open': 10, 'high': 15, 'low': 9, 'close': 12, 'volume': 1},
        {'timestamp': pd.to_datetime(2000, unit='ms'), 'open': 12, 'high': 18, 'low': 11, 'close': 15, 'volume': 2}
    ])
    data_engine.data[("BTC/USDT", "1m")] = initial_df
    
    # 1. Duplicate (timestamp 2000)
    dup_event = KlineEvent("BTC/USDT", "1m", 2000, 12, 18, 11, 15.5, 2, True)
    df = await data_engine.update_ohlcv(dup_event)
    assert len(df) == 2
    assert df.iloc[-1]["close"] == 15.5 # Kept last (overwrite)
    
    # 2. Out-of-order (timestamp 1500)
    ooo_event = KlineEvent("BTC/USDT", "1m", 1500, 11, 13, 10, 11.5, 1, True)
    df = await data_engine.update_ohlcv(ooo_event)
    assert len(df) == 3
    assert df.iloc[1]["timestamp"] == pd.to_datetime(1500, unit='ms')

@pytest.mark.asyncio
async def test_rolling_window_limit(data_engine, mock_exchange):
    # Limit is 5 as per fixture
    # Load 5 candles
    initial_data = [
        {'timestamp': pd.to_datetime(i*1000, unit='ms'), 'open': 10, 'high': 15, 'low': 9, 'close': 10+i, 'volume': 1}
        for i in range(5)
    ]
    data_engine.data[("BTC/USDT", "1m")] = pd.DataFrame(initial_data)
    
    # Add 6th candle
    event = KlineEvent("BTC/USDT", "1m", 6000, 20, 21, 19, 20.5, 1, True)
    df = await data_engine.update_ohlcv(event)
    
    assert len(df) == 5
    assert df.iloc[0]["timestamp"] == pd.to_datetime(1000, unit='ms') # 0th (1000ms) dropped, 1st remains
    assert df.iloc[-1]["timestamp"] == pd.to_datetime(6000, unit='ms')
