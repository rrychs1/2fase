import pytest
import pandas as pd
import numpy as np
from backtesting.sim_broker import SimBroker, SimPosition, SimTrade
from backtesting.metrics import calculate_metrics, BacktestMetrics
from backtesting.backtest_engine import BacktestEngine
from common.types import Signal, SignalAction, Side


@pytest.fixture
def broker():
    return SimBroker(
        initial_balance=10000.0,
        maker_fee=0.0004,  # 0.04%
        taker_fee=0.0006,  # 0.06%
        slippage=0.001,  # 0.1% (larger for visibility)
    )


def test_broker_fees_and_slippage_market_long(broker):
    # Test MARKET BUY (ENTER_LONG)
    signal = Signal(
        symbol="BTC/USDT",
        action=SignalAction.ENTER_LONG,
        side=Side.LONG,
        price=100.0,
        amount=10.0,
    )
    # Market fill at 100.0 + 0.1% slippage = 100.1
    # Fee: 100.1 * 10 * 0.0006 = 0.6006

    broker._open_position(signal, 100.0, candle_idx=0)

    pos = broker.positions["BTC/USDT"]
    assert pos.average_price == pytest.approx(100.1)
    assert broker.balance == pytest.approx(10000.0 - 0.6006)

    # Test MARKET SELL (EXIT_LONG)
    # Market exit at 110.0 - 0.1% slippage = 109.89
    # PnL: (109.89 - 100.1) * 10 = 97.9
    # Exit Fee (Taker): 109.89 * 10 * 0.0006 = 0.65934
    # Expected Balance: 9999.3994 + (97.9 - 0.65934) = 10096.64006

    broker._close_position("BTC/USDT", 110.0, candle_idx=1)
    assert broker.balance == pytest.approx(10096.64006)
    assert len(broker.trades) == 1
    assert broker.trades[0].pnl == pytest.approx(97.9)
    assert broker.trades[0].fees == pytest.approx(0.65934)


def test_broker_fees_and_slippage_limit_order(broker):
    # Test LIMIT fill (from pending order)
    # Limit orders should NOT have slippage but DO have maker fees
    broker.pending_orders.append(
        pytest.importorskip("backtesting.sim_broker").SimOrder(
            symbol="BTC/USDT", side="LONG", price=100.0, amount=10.0
        )
    )

    candle = {"symbol": "BTC/USDT", "open": 101, "high": 102, "low": 99, "close": 100}
    broker.update_on_candle(candle, candle_idx=0)

    # Fill at 100.0 (no slippage)
    # Maker Fee: 100 * 10 * 0.0004 = 0.4
    assert "BTC/USDT" in broker.positions
    assert broker.positions["BTC/USDT"].average_price == 100.0
    assert broker.balance == pytest.approx(10000.0 - 0.4)


def test_broker_sl_tp_triggering(broker):
    # Setup position
    broker.positions["BTC/USDT"] = SimPosition(
        symbol="BTC/USDT",
        side="LONG",
        entry_price=100.0,
        average_price=100.0,
        amount=10.0,
        stop_loss=95.0,
        take_profit=110.0,
    )

    # 1. Candle doesn't touch SL/TP
    broker.update_on_candle(
        {"symbol": "BTC/USDT", "open": 100, "high": 105, "low": 97, "close": 102}, 0
    )
    assert "BTC/USDT" in broker.positions

    # 2. Candle touches TP
    broker.update_on_candle(
        {"symbol": "BTC/USDT", "open": 102, "high": 111, "low": 101, "close": 105}, 1
    )
    assert "BTC/USDT" not in broker.positions
    assert len(broker.trades) == 1
    # Exit price should be the TP level PLUS slippage?
    # Actually, in SimBroker, TP exits are market orders on the level:
    # exit_price = 110.0, slippage applied as 110.0 * (1 - 0.001) = 109.89
    assert broker.trades[0].exit_price == pytest.approx(109.89)


def test_metrics_calculation():
    # Deterministic trades and equity
    # Trade 1: Gross PnL +100, Fees 10 -> Net PnL +90
    # Trade 2: Gross PnL -50, Fees 5 -> Net PnL -55
    trades = [
        SimTrade(
            symbol="BTC",
            side="LONG",
            entry_price=100,
            exit_price=110,
            amount=10,
            pnl=100,
            pnl_after_fees=90,
            fees=10,
        ),
        SimTrade(
            symbol="BTC",
            side="LONG",
            entry_price=100,
            exit_price=95,
            amount=10,
            pnl=-50,
            pnl_after_fees=-55,
            fees=5,
        ),
    ]
    equity_curve = [1000, 1090, 1035]

    metrics = calculate_metrics(
        equity_curve=equity_curve,
        trades=trades,
        initial_equity=1000.0,
        buy_hold_start_price=100.0,
        buy_hold_end_price=110.0,
        candles_per_day=6.0,
    )

    assert metrics.total_pnl == 35.0
    assert metrics.total_return_pct == 3.5
    assert metrics.win_rate == 50.0
    assert metrics.profit_factor == 1.636
    assert metrics.max_drawdown_abs == 55.0
    # DD = (1090 - 1035) / 1090 = 5.045%
    assert metrics.max_drawdown_pct == pytest.approx(5.04587, rel=1e-3)


@pytest.mark.asyncio
async def test_backtest_engine_integration():
    # Create simple oscillating data
    data = []
    base_price = 100.0
    for i in range(300):
        # Bullish trend with pullback
        price = base_price + i * 0.1 if i < 150 else base_price + 15 - (i - 150) * 0.2
        data.append(
            {
                "timestamp": i * 3600,
                "open": price,
                "high": price + 0.5,
                "low": price - 0.5,
                "close": price,
                "volume": 1000,
            }
        )
    df = pd.DataFrame(data)

    engine = BacktestEngine(
        symbol="BTC/USDT", timeframe="1h", initial_balance=10000.0, lookback=50
    )

    # We don't necessarily care about the strategy success here,
    # but rather that the loop executes without error and produces a result.
    metrics = engine.run(df)

    assert isinstance(metrics, BacktestMetrics)
    assert len(engine.broker.equity_curve) == len(df) - 50 + 1  # +1 for initial
    assert metrics.initial_equity == 10000.0
