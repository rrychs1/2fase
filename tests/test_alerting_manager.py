import pytest
import asyncio
import json
import os
import time
from unittest.mock import MagicMock, patch, AsyncMock
from core.alerting_manager import AlertManager

@pytest.fixture
def temp_history_file(tmp_path):
    return str(tmp_path / "alert_history.jsonl")

@pytest.fixture
def alert_manager(temp_history_file):
    # Mock environment variables
    with patch.dict(os.environ, {
        "DISCORD_WEBHOOK_URL": "http://mock.discord",
        "TELEGRAM_WEBHOOK_URL": "http://mock.telegram",
        "SMTP_SERVER": "smtp.mock.com",
        "SMTP_SENDER": "bot@test.com",
        "SMTP_PASSWORD": "pass",
        "ALERT_RECIPIENT_EMAIL": "admin@test.com"
    }):
        manager = AlertManager(history_file=temp_history_file)
        return manager

@pytest.mark.asyncio
async def test_alert_persistence(alert_manager, temp_history_file):
    await alert_manager.send_alert("Strategy1", "Test Message", "INFO")
    await asyncio.sleep(0.01)
    
    assert os.path.exists(temp_history_file)
    with open(temp_history_file, "r") as f:
        line = f.readline()
        data = json.loads(line)
        assert data["strategy_id"] == "Strategy1"
        assert data["message"] == "Test Message"
        assert data["severity"] == "INFO"

@pytest.mark.asyncio
async def test_alert_deduplication_cooldown(alert_manager):
    # Mocking dispatch methods to count calls
    alert_manager._dispatch_webhook = AsyncMock()
    
    # Send first alert
    await alert_manager.send_alert("Strategy1", "Duplicate Message", "WARNING")
    await asyncio.sleep(0.01) # Wait for async task to start
    assert alert_manager._dispatch_webhook.call_count == 2 # Discord + Telegram
    
    # Send same alert immediately -> should be blocked by cooldown
    await alert_manager.send_alert("Strategy1", "Duplicate Message", "WARNING")
    await asyncio.sleep(0.01)
    assert alert_manager._dispatch_webhook.call_count == 2
    
    # Change severity -> should be a different hash
    await alert_manager.send_alert("Strategy1", "Duplicate Message", "CRITICAL")
    await asyncio.sleep(0.01)
    assert alert_manager._dispatch_webhook.call_count == 4

@pytest.mark.asyncio
async def test_alert_severity_cooldowns(alert_manager):
    alert_manager._dispatch_webhook = AsyncMock()
    
    # Set a very short cooldown for testing if needed, or just mock time
    with patch('time.time') as mock_time:
        mock_time.return_value = 1000.0
        await alert_manager.send_alert("S1", "Msg", "CRITICAL")
        await asyncio.sleep(0.01)
        assert alert_manager._dispatch_webhook.call_count == 2
        
        # 10 seconds later, still in cooldown (CRITICAL is 300s)
        mock_time.return_value = 1010.0
        await alert_manager.send_alert("S1", "Msg", "CRITICAL")
        await asyncio.sleep(0.01)
        assert alert_manager._dispatch_webhook.call_count == 2
        
        # 301 seconds later, cooldown expired
        mock_time.return_value = 1301.0
        await alert_manager.send_alert("S1", "Msg", "CRITICAL")
        await asyncio.sleep(0.01)
        assert alert_manager._dispatch_webhook.call_count == 4

@pytest.mark.asyncio
async def test_async_dispatch_non_blocking(alert_manager):
    # Mock a slow webhook
    async def slow_dispatch(*args):
        await asyncio.sleep(0.1)
        
    alert_manager._dispatch_webhook = AsyncMock(side_effect=slow_dispatch)
    
    start_time = time.perf_counter()
    await alert_manager.send_alert("S1", "Msg", "INFO")
    end_time = time.perf_counter()
    
    # The send_alert method should return almost immediately because it uses create_task for dispatch
    assert end_time - start_time < 0.05
    # The task will run in background.
