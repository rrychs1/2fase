import pytest
from logging_monitoring.metrics_server import (
    bot_total_trades, bot_winning_trades, bot_realized_pnl,
    bot_unrealized_pnl, bot_daily_drawdown_pct, bot_current_exposure,
    bot_system_health, bot_ws_connected
)
from execution.portfolio_engine import Portfolio

def test_prometheus_counters_in_portfolio():
    # Setup
    port = Portfolio(initial_balance=10000.0, fee_rate=0.0, slippage_rate=0.0)
    
    # Store initial counter values so test doesn't fail if other tests ran
    before_trades = bot_total_trades._value.get()
    before_wins = bot_winning_trades._value.get()
    
    # Simulate a winning trade
    port.open_position("BTC/USDT", "LONG", 50000.0, 1.0)
    port.close_position("BTC/USDT", 51000.0)
    
    assert bot_total_trades._value.get() == before_trades + 1
    assert bot_winning_trades._value.get() == before_wins + 1
    assert bot_realized_pnl._value.get() == 1000.0
    
    # Simulate a losing trade
    port.open_position("ETH/USDT", "LONG", 2000.0, 1.0)
    port.close_position("ETH/USDT", 1800.0)
    
    assert bot_total_trades._value.get() == before_trades + 2
    assert bot_winning_trades._value.get() == before_wins + 1 # Did not increment
    assert bot_realized_pnl._value.get() == 800.0 # 1000 - 200

def test_gauges_have_labels():
    # Just verify they are imported and accessible
    bot_unrealized_pnl.set(150.5)
    assert bot_unrealized_pnl._value.get() == 150.5
    
    bot_system_health.set(1)
    assert bot_system_health._value.get() == 1
