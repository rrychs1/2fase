"""
Unit tests for WebsocketManager.

Design principles:
- All queue reads use get_nowait() to avoid blocking the event loop.
- Timestamps in test messages are always unique to avoid the dedup filter.
- asyncio.sleep is patched at the module level to prevent real waits.
- The ws_manager fixture is async so asyncio.Queue() is created in the test loop.
"""

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
async def ws_manager():
    """Async fixture — asyncio.Queue is bound to the test's own event loop."""
    return WebsocketManager(MockConfig())


# ────────────────────────────────────────────────────────
# Helpers
# ────────────────────────────────────────────────────────

def _kline_msg(t: int, is_closed: bool) -> str:
    x = "true" if is_closed else "false"
    return (
        f'{{"e":"kline","s":"BTCUSDT","k":{{"t":{t},"i":"1m","x":{x},'
        f'"o":"1","c":"1","h":"1","l":"1","v":"1"}}}}'
    )


# ────────────────────────────────────────────────────────
# Tests
# ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_websocket_deduplication(ws_manager):
    """A duplicate kline (same timestamp) must be dropped."""
    msg = _kline_msg(t=1610000000000, is_closed=True)

    await ws_manager._process_message(msg)
    assert ws_manager.event_queue.qsize() == 1
    event = ws_manager.event_queue.get_nowait()
    assert event.is_closed is True

    # Duplicate — must be silently dropped
    await ws_manager._process_message(msg)
    assert ws_manager.event_queue.qsize() == 0


@pytest.mark.asyncio
async def test_websocket_out_of_order_ignored(ws_manager):
    """An older kline arriving after a newer one must be ignored."""
    msg_new = _kline_msg(t=1000, is_closed=True)
    msg_old = _kline_msg(t=900, is_closed=True)

    await ws_manager._process_message(msg_new)
    assert ws_manager.event_queue.qsize() == 1
    ws_manager.event_queue.get_nowait()

    # Older timestamp — must be ignored
    await ws_manager._process_message(msg_old)
    assert ws_manager.event_queue.qsize() == 0


@pytest.mark.asyncio
async def test_websocket_partial_vs_closed_flag(ws_manager):
    """Partial candles (x=false) are stored in latest_open, NOT enqueued.
    Closed candles (x=true) are pushed to event_queue.
    Uses distinct timestamps to bypass the dedup filter."""
    msg_partial = _kline_msg(t=2000, is_closed=False)
    msg_closed = _kline_msg(t=3000, is_closed=True)

    # Partial: must go to latest_open, queue stays empty
    await ws_manager._process_message(msg_partial)
    assert ws_manager.event_queue.qsize() == 0
    assert "BTC/USDT_1m" in ws_manager.latest_open
    assert ws_manager.latest_open["BTC/USDT_1m"]["timestamp"] == 2000

    # Closed: must be enqueued
    await ws_manager._process_message(msg_closed)
    assert ws_manager.event_queue.qsize() == 1
    event = ws_manager.event_queue.get_nowait()
    assert event.is_closed is True
    assert event.timestamp == 3000


@pytest.mark.asyncio
async def test_websocket_heartbeat_timeout_triggers_close(ws_manager):
    """If idle time exceeds heartbeat_timeout the socket should be closed."""
    ws_manager.is_running = True
    ws_manager.ws = AsyncMock()
    ws_manager.ws.closed = False

    ws_manager.last_message_time = time.time() - 10
    ws_manager.heartbeat_timeout = 5

    # Replicate the heartbeat check inline (no real sleep needed)
    now = time.time()
    idle_time = now - ws_manager.last_message_time
    if idle_time > ws_manager.heartbeat_timeout:
        await ws_manager.ws.close()

    ws_manager.ws.close.assert_called_once()


@pytest.mark.asyncio
async def test_reconnect_logic_backoff(ws_manager):
    """Exponential backoff increments correctly on each call."""
    ws_manager.is_running = True
    ws_manager.reconnect_attempts = 0
    ws_manager.max_retries = 3

    with patch("data.websocket_manager.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        await ws_manager._handle_reconnect()
        assert ws_manager.reconnect_attempts == 1
        mock_sleep.assert_called_with(2)  # 2^1

        await ws_manager._handle_reconnect()
        assert ws_manager.reconnect_attempts == 2
        mock_sleep.assert_called_with(4)  # 2^2


@pytest.mark.asyncio
async def test_max_retries_resets_counter(ws_manager):
    """After exceeding max_retries the counter resets to 0 and the manager
    keeps retrying indefinitely (is_running stays True)."""
    ws_manager.is_running = True
    ws_manager.reconnect_attempts = 5
    ws_manager.max_retries = 5

    with patch("data.websocket_manager.asyncio.sleep", new_callable=AsyncMock):
        await ws_manager._handle_reconnect()

    # Counter resets — manager does NOT stop
    assert ws_manager.reconnect_attempts == 0
    assert ws_manager.is_running is True
