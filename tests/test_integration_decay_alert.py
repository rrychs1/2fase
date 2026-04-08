import pytest
import pandas as pd
import numpy as np
import asyncio
from unittest.mock import AsyncMock, patch, MagicMock
from analysis.strategy_decay_monitor import StrategyDecayMonitor
from core.alerting_manager import AlertManager


@pytest.fixture
def mock_alert_manager():
    manager = MagicMock(spec=AlertManager)
    manager.send_alert = AsyncMock()
    return manager


@pytest.fixture
def decaying_trades():
    # Generate historical baseline (good)
    n_baseline = 100
    baseline_returns = np.random.normal(0.001, 0.01, n_baseline)

    # Recent data (decaying - negative drift)
    n_recent = 50
    recent_returns = np.random.normal(-0.005, 0.02, n_recent)

    returns = np.concatenate([baseline_returns, recent_returns])
    trades = pd.DataFrame(
        {
            "net_pnl": returns,
            "exit_time": pd.date_range(
                start="2023-01-01", periods=len(returns), freq="h"
            ),
        }
    )
    return trades


@pytest.mark.asyncio
async def test_integration_decay_triggers_alert(mock_alert_manager, decaying_trades):
    # Initialize monitor with mock alert manager
    monitor = StrategyDecayMonitor(alert_manager=mock_alert_manager)

    # Configure strategy with aggressive thresholds to ensure alert triggers
    config = {
        "min_trades": 50,
        "recent_window": 30,
        "health_warning_threshold": 80.0,  # High threshold to trigger alert easily
    }
    monitor.register_strategy("DecayingBot", config_overrides=config)

    # Update trades
    monitor.update_trades("DecayingBot", decaying_trades)

    # Evaluate and trigger alerts
    results = await monitor.check_all_strategies()

    # Verify results
    assert len(results) == 1
    assert results[0]["strategy_id"] == "DecayingBot"
    assert len(results[0]["alerts"]) > 0

    # Verify AlertManager was called
    assert mock_alert_manager.send_alert.called
    # Check severity mapping
    args, kwargs = mock_alert_manager.send_alert.call_args
    assert kwargs["strategy_id"] == "DecayingBot"
    assert kwargs["severity"] in ["WARNING", "CRITICAL"]
    assert "health_score" in kwargs["metadata"]


@pytest.mark.asyncio
async def test_monitor_works_without_alert_manager(decaying_trades):
    # Initialize without alert manager
    monitor = StrategyDecayMonitor(alert_manager=None)
    monitor.register_strategy("StandaloneBot")
    monitor.update_trades("StandaloneBot", decaying_trades)

    # Should not raise exception
    results = await monitor.check_all_strategies()
    assert results is not None
