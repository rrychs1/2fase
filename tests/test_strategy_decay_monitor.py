import pytest
import pandas as pd
import numpy as np
from analysis.strategy_decay_monitor import StrategyDecayMonitor


def generate_mock_trades(n_good, n_bad):
    good_pnl = np.random.normal(2, 5, n_good)
    bad_pnl = np.random.normal(-5, 2, n_bad)
    pnl = np.concatenate([good_pnl, bad_pnl])
    return pd.DataFrame({"net_pnl": pnl})


def test_singleton_registration():
    monitor = StrategyDecayMonitor()
    monitor.register_strategy("Trend_Bot", {"health_critical_threshold": 20.0})

    assert "Trend_Bot" in monitor.strategies
    assert (
        monitor.strategies["Trend_Bot"]["config"]["health_critical_threshold"] == 20.0
    )


def test_sigmoid_scaling():
    monitor = StrategyDecayMonitor()

    # 0 should be highly healthy ~ 90-95
    h_good = monitor.zscore_to_health_score(0.0)
    assert h_good > 90.0

    # -1.5 is the midpoint
    h_mid = monitor.zscore_to_health_score(-1.5)
    assert 40.0 < h_mid < 60.0  # roughly 50

    # -3.0 should be totally dead (close to 0)
    h_dead = monitor.zscore_to_health_score(-3.0)
    assert h_dead < 15.0


@pytest.mark.asyncio
async def test_decay_monitor_alerts():
    np.random.seed(42)
    monitor = StrategyDecayMonitor()

    # Create two bots
    monitor.register_strategy("Good_Bot")
    monitor.register_strategy("Dying_Bot")

    # Good bot has stationary performance
    good_df = pd.DataFrame({"net_pnl": np.random.normal(5, 5, 500)})

    # Dying bot has 400 good trades, and 100 dead trades
    dying_df = generate_mock_trades(400, 100)

    monitor.update_trades("Good_Bot", good_df)
    monitor.update_trades("Dying_Bot", dying_df)

    alerts = await monitor.check_all_strategies()

    # Only Dying Bot should be in the alerts array
    assert len(alerts) == 1
    assert alerts[0]["strategy_id"] == "Dying_Bot"

    # Score should be incredibly low
    assert alerts[0]["health_score"] < 40.0

    alert_types = [a["type"] for a in alerts[0]["alerts"]]
    assert "CRITICAL" in alert_types or "WARNING" in alert_types


def test_rapid_deterioration_state_memory():
    np.random.seed(42)
    monitor = StrategyDecayMonitor()
    monitor.register_strategy("Sudden_Death_Bot", {"deterioration_warning_drop": 15.0})

    # State 1: Highly profitable
    df_state1 = pd.DataFrame({"net_pnl": np.random.normal(5, 5, 500)})
    monitor.update_trades("Sudden_Death_Bot", df_state1)
    res1 = monitor.evaluate_strategy_health("Sudden_Death_Bot")

    assert res1["health_score"] > 80.0
    assert len(res1["alerts"]) == 0

    # State 2: Market violently shifts, last 50 trades are garbage
    df_state2 = generate_mock_trades(500, 50)
    monitor.update_trades("Sudden_Death_Bot", df_state2)
    res2 = monitor.evaluate_strategy_health("Sudden_Death_Bot")

    # Health should have plummeted from ~90 down.
    alerts = res2["alerts"]
    alert_msgs = [a["message"] for a in alerts]

    # Ensure rapid deterioration rule fired
    assert any("Rapid Deterioration Detected" in msg for msg in alert_msgs)


def test_false_alert_prevention_stationary_strategy():
    np.random.seed(42)
    monitor = StrategyDecayMonitor()
    monitor.register_strategy("Stable_But_Volatile_Bot")

    # Create a stationary but volatile distribution (Normal dist with high variance but positive mean)
    # The LAW of LARGE NUMBERS should keep the z-score near 0, preventing alerts.
    df_history = pd.DataFrame({"net_pnl": np.random.normal(5, 10, 500)})
    monitor.update_trades("Stable_But_Volatile_Bot", df_history)

    res = monitor.evaluate_strategy_health("Stable_But_Volatile_Bot")

    # Despite the high volatility, the health should be stable if the distribution hasn't shifted
    assert res["health_score"] > 80.0
    assert len(res["alerts"]) == 0
    assert res["status"] == "NORMAL"
