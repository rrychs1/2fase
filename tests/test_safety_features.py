import pytest
import os
import time
from datetime import date, timedelta
from unittest.mock import patch, AsyncMock
from risk.risk_manager import RiskManager
from exchange.exchange_client import ExchangeClient
from config.config_loader import Config


class MockConfig(Config):
    KILL_SWITCH_ENABLED = True
    DAILY_LOSS_LIMIT = 0.10
    TRADING_ENV = "SIM"
    USE_TESTNET = True


@pytest.fixture
def risk_manager():
    config = MockConfig()
    if os.path.exists("risk_state.json"):
        os.remove("risk_state.json")
    if os.path.exists(".kill_switch_lock"):
        os.remove(".kill_switch_lock")
    rm = RiskManager(config)
    yield rm
    # Cleanup files
    if os.path.exists(rm.state_file):
        os.remove(rm.state_file)
    if os.path.exists(rm.lock_file):
        os.remove(rm.lock_file)


def test_hard_kill_switch_creation_and_blocking(risk_manager):
    # Simulate $1000 equity, PnL is -$150 (exceeds 10% limit)
    risk_manager.day_start_equity = 1000.0
    risk_manager.check_daily_drawdown(-150.0, 1000.0)

    # 1. Assert memory state
    assert risk_manager.is_kill_switch_active == True

    # 2. Assert disk hard lock creation
    assert os.path.exists(risk_manager.lock_file)

    with open(risk_manager.lock_file, "r") as f:
        locked_date = f.read().strip()
    assert locked_date == date.today().isoformat()

    # 3. Simulate Crash and Reboot
    new_rm = RiskManager(MockConfig())
    assert new_rm.is_kill_switch_active == True


def test_hard_kill_switch_auto_reset(risk_manager):
    # Create an old lock file from "yesterday"
    yesterday_str = (date.today() - timedelta(days=1)).isoformat()
    with open(risk_manager.lock_file, "w") as f:
        f.write(yesterday_str)

    # Reboot risk manager
    new_rm = RiskManager(MockConfig())

    # The lock should be deleted and trading resumed
    assert new_rm.is_kill_switch_active == False
    assert not os.path.exists(new_rm.lock_file)


@pytest.mark.asyncio
async def test_api_jitter_backoff():
    # Test random jitter in ExchangeClient using CCXT rate limits
    client = ExchangeClient()

    # Mocking multiplier scaling from previous 429
    client.backoff_multiplier = 2.0

    with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        await client._apply_backoff()
        mock_sleep.assert_called_once()

        args, _ = mock_sleep.call_args
        sleep_time = args[0]

        # Original delay = min(30, (2 - 1) * 2) = 2.0s
        # Jitter uniform(0.1, 1.5)
        assert 2.1 <= sleep_time <= 3.5
