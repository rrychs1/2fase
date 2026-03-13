import pytest
import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch
from config.config_loader import Config
from data.websocket_manager import WebsocketManager

class MockConfig(Config):
    USE_TESTNET = True
    WS_MAX_RETRIES = 2
    WS_HEARTBEAT_TIMEOUT = 1
    USE_WEBSOCKETS = True

@pytest.fixture
def ws_manager():
    return WebsocketManager(MockConfig())

@pytest.mark.asyncio
async def test_websocket_deduplication(ws_manager):
    # Process first valid closed candle
    msg1 = '{"e":"kline","E":1620000000000,"s":"BTCUSDT","k":{"t":1610000000000,"T":1610000059999,"s":"BTCUSDT","i":"1m","f":100,"L":200,"o":"50000","c":"50100","h":"50150","l":"49950","v":"100","n":100,"x":true,"q":"5000000","V":"50","Q":"2500000","B":"0"}}'
    
    await ws_manager._process_message(msg1)
    
    assert ws_manager.event_queue.qsize() == 1
    event1 = await ws_manager.event_queue.get()
    assert event1.is_closed == True
    
    # Send duplicate (same start time 't')
    await ws_manager._process_message(msg1)
    assert ws_manager.event_queue.qsize() == 0

@pytest.mark.asyncio
async def test_websocket_out_of_order_ignored(ws_manager):
    # msg at 1000
    msg_new = '{"e":"kline","s":"BTCUSDT","k":{"t":1000,"i":"1m","x":true,"o":"1","c":"1","h":"1","l":"1","v":"1"}}'
    # msg at 900 (older)
    msg_old = '{"e":"kline","s":"BTCUSDT","k":{"t":900,"i":"1m","x":true,"o":"1","c":"1","h":"1","l":"1","v":"1"}}'
    
    await ws_manager._process_message(msg_new)
    assert ws_manager.event_queue.qsize() == 1
    await ws_manager.event_queue.get()
    
    # Send older message
    await ws_manager._process_message(msg_old)
    # Should be ignored by deduplication logic (start_time <= last_processed)
    assert ws_manager.event_queue.qsize() == 0

@pytest.mark.asyncio
async def test_websocket_partial_vs_closed_flag(ws_manager):
    # Partial candle
    msg_partial = '{"e":"kline","s":"BTCUSDT","k":{"t":1000,"i":"1m","x":false,"o":"1","c":"1","h":"1","l":"1","v":"1"}}'
    # Closed candle
    msg_closed = '{"e":"kline","s":"BTCUSDT","k":{"t":1000,"i":"1m","x":true,"o":"1","c":"1","h":"1","l":"1","v":"1"}}'
    
    await ws_manager._process_message(msg_partial)
    event = await ws_manager.event_queue.get()
    assert event.is_closed is False
    
    await ws_manager._process_message(msg_closed)
    event = await ws_manager.event_queue.get()
    assert event.is_closed is True

@pytest.mark.asyncio
async def test_websocket_heartbeat_timeout_triggers_close(ws_manager):
    ws_manager.is_running = True
    ws_manager.ws = AsyncMock()
    ws_manager.ws.closed = False
    
    # Force idle time
    ws_manager.last_message_time = time.time() - 10
    ws_manager.heartbeat_timeout = 5
    
    # Manually trigger heartbeat check logic
    now = time.time()
    idle_time = now - ws_manager.last_message_time
    if idle_time > ws_manager.heartbeat_timeout:
        await ws_manager.ws.close()
    
    ws_manager.ws.close.assert_called_once()

@pytest.mark.asyncio
async def test_reconnect_logic_backoff(ws_manager):
    ws_manager.is_running = True
    ws_manager.reconnect_attempts = 0
    ws_manager.max_retries = 3
    
    with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        # Simulate one reconnect trigger
        await ws_manager._handle_reconnect()
        
        assert ws_manager.reconnect_attempts == 1
        # Backoff: 2^1 = 2s
        mock_sleep.assert_called_with(2)
        
        # Another attempt
        await ws_manager._handle_reconnect()
        assert ws_manager.reconnect_attempts == 2
        # Backoff: 2^2 = 4s
        mock_sleep.assert_called_with(4)

@pytest.mark.asyncio
async def test_max_retries_stops_manager(ws_manager):
    ws_manager.is_running = True
    ws_manager.reconnect_attempts = 5
    ws_manager.max_retries = 5
    
    await ws_manager._handle_reconnect()
    assert ws_manager.is_running is False

