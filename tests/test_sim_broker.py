"""Tests for backtesting/sim_broker.py."""

import pytest
from common.types import Signal, SignalAction, Side
from backtesting.sim_broker import SimBroker


@pytest.fixture
def broker():
    return SimBroker(
        initial_balance=10000.0, maker_fee=0.0004, taker_fee=0.0006, slippage=0.0001
    )


class TestOpenPosition:
    def test_open_long_deducts_fee(self, broker):
        sig = Signal(
            symbol="BTC/USDT",
            action=SignalAction.ENTER_LONG,
            side=Side.LONG,
            price=60000.0,
            amount=0.1,
            stop_loss=58000.0,
            take_profit=64000.0,
        )
        broker.process_signal(sig, current_price=60000.0)
        # Fee = 60000 * (1 + 0.01%) * 0.1 * 0.06% ≈ 3.60
        assert broker.balance < 10000.0
        assert "BTC/USDT" in broker.positions

    def test_open_short(self, broker):
        sig = Signal(
            symbol="BTC/USDT",
            action=SignalAction.ENTER_SHORT,
            side=Side.SHORT,
            price=60000.0,
            amount=0.1,
        )
        broker.process_signal(sig, current_price=60000.0)
        assert broker.positions["BTC/USDT"].side == "SHORT"

    def test_no_duplicate_position(self, broker):
        sig = Signal(
            symbol="BTC/USDT",
            action=SignalAction.ENTER_LONG,
            side=Side.LONG,
            price=60000.0,
            amount=0.1,
        )
        broker.process_signal(sig, current_price=60000.0)
        # Second entry should be ignored
        broker.process_signal(sig, current_price=61000.0)
        assert broker.positions["BTC/USDT"].entry_price == pytest.approx(
            60000 * 1.0001, rel=1e-3
        )

    def test_zero_amount_ignored(self, broker):
        sig = Signal(
            symbol="BTC/USDT",
            action=SignalAction.ENTER_LONG,
            side=Side.LONG,
            price=60000.0,
            amount=0.0,
        )
        broker.process_signal(sig, current_price=60000.0)
        assert "BTC/USDT" not in broker.positions


class TestClosePosition:
    def test_close_long_profit(self, broker):
        # Open
        sig = Signal(
            symbol="BTC/USDT",
            action=SignalAction.ENTER_LONG,
            side=Side.LONG,
            price=60000.0,
            amount=0.1,
        )
        broker.process_signal(sig, current_price=60000.0)
        # Close at higher price
        close_sig = Signal(
            symbol="BTC/USDT",
            action=SignalAction.EXIT_LONG,
            side=Side.LONG,
            price=62000.0,
        )
        broker.process_signal(close_sig, current_price=62000.0)
        assert "BTC/USDT" not in broker.positions
        assert len(broker.trades) == 1
        assert broker.trades[0].pnl > 0

    def test_close_long_loss(self, broker):
        sig = Signal(
            symbol="BTC/USDT",
            action=SignalAction.ENTER_LONG,
            side=Side.LONG,
            price=60000.0,
            amount=0.1,
        )
        broker.process_signal(sig, current_price=60000.0)
        close_sig = Signal(
            symbol="BTC/USDT", action=SignalAction.EXIT_LONG, side=Side.LONG
        )
        broker.process_signal(close_sig, current_price=58000.0)
        assert broker.trades[0].pnl < 0


class TestStopLossAndTakeProfit:
    def test_sl_triggers_long(self, broker):
        sig = Signal(
            symbol="BTC/USDT",
            action=SignalAction.ENTER_LONG,
            side=Side.LONG,
            price=60000.0,
            amount=0.1,
            stop_loss=58000.0,
            take_profit=64000.0,
        )
        broker.process_signal(sig, current_price=60000.0)
        # Candle hits SL
        broker.update_on_candle(
            {
                "symbol": "BTC/USDT",
                "open": 59000,
                "high": 59500,
                "low": 57500,
                "close": 58500,
            }
        )
        assert "BTC/USDT" not in broker.positions
        assert len(broker.trades) == 1

    def test_tp_triggers_long(self, broker):
        sig = Signal(
            symbol="BTC/USDT",
            action=SignalAction.ENTER_LONG,
            side=Side.LONG,
            price=60000.0,
            amount=0.1,
            stop_loss=58000.0,
            take_profit=64000.0,
        )
        broker.process_signal(sig, current_price=60000.0)
        # Candle hits TP
        broker.update_on_candle(
            {
                "symbol": "BTC/USDT",
                "open": 63000,
                "high": 65000,
                "low": 62000,
                "close": 64500,
            }
        )
        assert "BTC/USDT" not in broker.positions
        assert broker.trades[0].pnl > 0

    def test_none_sl_tp_no_crash(self, broker):
        sig = Signal(
            symbol="BTC/USDT",
            action=SignalAction.ENTER_LONG,
            side=Side.LONG,
            price=60000.0,
            amount=0.1,
        )
        broker.process_signal(sig, current_price=60000.0)
        # No SL/TP -> should not close
        broker.update_on_candle(
            {
                "symbol": "BTC/USDT",
                "open": 50000,
                "high": 70000,
                "low": 50000,
                "close": 60000,
            }
        )
        assert "BTC/USDT" in broker.positions


class TestPendingOrders:
    def test_grid_order_fills_on_price_cross(self, broker):
        # Place grid buy at 59000
        sig = Signal(
            symbol="BTC/USDT",
            action=SignalAction.GRID_PLACE,
            side=Side.LONG,
            price=59000.0,
            amount=0.05,
        )
        broker.process_signal(sig, current_price=60000.0)
        assert len(broker.pending_orders) == 1
        # Candle touches 59000
        broker.update_on_candle(
            {
                "symbol": "BTC/USDT",
                "open": 60000,
                "high": 60000,
                "low": 58500,
                "close": 59500,
            }
        )
        assert len(broker.pending_orders) == 0
        assert "BTC/USDT" in broker.positions

    def test_grid_order_no_fill_if_price_doesnt_cross(self, broker):
        sig = Signal(
            symbol="BTC/USDT",
            action=SignalAction.GRID_PLACE,
            side=Side.LONG,
            price=55000.0,
            amount=0.05,
        )
        broker.process_signal(sig, current_price=60000.0)
        broker.update_on_candle(
            {
                "symbol": "BTC/USDT",
                "open": 60000,
                "high": 61000,
                "low": 59000,
                "close": 60500,
            }
        )
        assert len(broker.pending_orders) == 1


class TestEquity:
    def test_unrealized_pnl_long(self, broker):
        sig = Signal(
            symbol="BTC/USDT",
            action=SignalAction.ENTER_LONG,
            side=Side.LONG,
            price=60000.0,
            amount=0.1,
        )
        broker.process_signal(sig, current_price=60000.0)
        eq = broker.get_equity_with_unrealized({"BTC/USDT": 62000.0})
        # Unrealized PnL = (62000 - 60006) * 0.1 ≈ +199.4
        assert eq > broker.balance

    def test_force_close_all(self, broker):
        sig = Signal(
            symbol="BTC/USDT",
            action=SignalAction.ENTER_LONG,
            side=Side.LONG,
            price=60000.0,
            amount=0.1,
        )
        broker.process_signal(sig, current_price=60000.0)
        broker.force_close_all({"BTC/USDT": 60000.0})
        assert len(broker.positions) == 0
        assert len(broker.trades) == 1
