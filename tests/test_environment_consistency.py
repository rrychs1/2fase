import pytest
import pandas as pd
import numpy as np
import datetime
import asyncio
from unittest.mock import AsyncMock, patch, MagicMock

from config.config_loader import Config
from backtesting.backtest_engine import BacktestEngine
from orchestration.bot_runner import BotRunner
from common.types import SignalAction
from execution.execution_router import ExecutionRouter


def generate_deterministic_ohlcv(candles=300) -> pd.DataFrame:
    np.random.seed(42)  # Strict deterministic dataset mapping
    dates = [
        datetime.datetime(2025, 1, 1) + datetime.timedelta(minutes=15 * i)
        for i in range(candles)
    ]

    # Generate a massive parabolic uptrend to force standard trend signals natively out of both engines
    close_prices = np.linspace(50000, 60000, candles) + np.random.normal(
        0, 100, candles
    )
    high_prices = close_prices + np.random.uniform(50, 200, candles)
    low_prices = close_prices - np.random.uniform(50, 200, candles)
    open_prices = np.roll(close_prices, 1)
    open_prices[0] = 49950
    volumes = np.random.uniform(1, 10, candles)

    df = pd.DataFrame(
        {
            "timestamp": dates,
            "open": open_prices,
            "high": high_prices,
            "low": low_prices,
            "close": close_prices,
            "volume": volumes,
        }
    )
    return df


@pytest.mark.asyncio
async def test_environment_consistency_parity():
    """
    Validates that the strict Offline Backtest Engine and the fully-simulated
    Asynchronous Live BotRunner generate mathematically identical signals
    and comparable PnL when fed identical static DataFrame chunks organically.
    """
    import os

    for file in [
        "virtual_account.json",
        "data/paper_trading_state.json",
        "data/bot_state.json",
        "data/bot_state.db",
        "data/dashboard_state.json",
    ]:
        if os.path.exists(file):
            try:
                os.remove(file)
            except Exception:
                pass

    df = generate_deterministic_ohlcv(300)
    symbol = "BTC/USDT"

    # ====================================================
    # 1. RUN BACKTEST ENGINE (Fully Offline Simulator)
    # ====================================================
    bt_engine = BacktestEngine(symbol=symbol, timeframe="15m", lookback=100)
    bt_engine.config.SYMBOLS = [symbol]

    # Override Strategy configs for deterministic parity tests
    bt_engine.config.TREND_DCA_ENABLED = True
    bt_engine.config.NEUTRAL_GRID_ENABLED = False
    bt_engine.config.TREND_MULTI_TIMEFRAME = False

    metrics = bt_engine.run(df)
    bt_trades = bt_engine.broker.trades
    bt_pnl = metrics.total_pnl
    bt_signals_count = len([t for t in bt_trades])

    # ====================================================
    # 2. RUN SIMULATED LIVE (Async Bot Runner / Paper)
    # ====================================================
    config = Config()
    config.ANALYSIS_ONLY = True  # strict Paper Mode bridging
    config.EXECUTION_MODE = "PAPER"
    config.SYMBOLS = [symbol]
    config.TF_GRID = "15m"
    config.TF_TREND = "15m"
    config.CANDLES_ANALYSIS_LIMIT = 300
    config.TREND_DCA_ENABLED = True
    config.NEUTRAL_GRID_ENABLED = False
    config.TREND_MULTI_TIMEFRAME = False

    live_signals_count = 0

    mock_exchange = MagicMock()
    mock_exchange.fetch_balance = AsyncMock(return_value={"total": {"USDT": 10000.0}})
    mock_exchange.init = AsyncMock()
    mock_exchange.fetch_open_orders = AsyncMock(return_value=[])
    mock_exchange.get_market_precision = MagicMock(return_value=(2, 4))

    bot = BotRunner(config=config, exchange=mock_exchange)
    bot.telegram = MagicMock()
    bot.telegram.is_healthy.return_value = True
    bot.telegram.info = AsyncMock()
    bot.telegram.trade = AsyncMock()
    bot.telegram.error = AsyncMock()
    bot.telegram.warning = AsyncMock()
    bot.telegram.critical = AsyncMock()

    # Intercept Router to strictly count logical signals
    original_route = bot.strategy_router.route_signals

    async def intercepted_route(sym, regime, state):
        nonlocal live_signals_count
        sigs = await original_route(sym, regime, state)
        for s in sigs:
            if s.action in [
                SignalAction.ENTER_LONG,
                SignalAction.ENTER_SHORT,
                SignalAction.EXIT_LONG,
                SignalAction.EXIT_SHORT,
            ]:
                live_signals_count += 1
        return sigs

    bot.strategy_router.route_signals = intercepted_route

    # Emulate WebSocket Time Progression Exactly:
    start_idx = 100
    for i in range(start_idx, len(df)):
        window = df.iloc[max(0, i - start_idx) : i + 1].copy()

        # Inject state organically to BotRunner DataEngine
        bot.data_engine.data[(symbol, config.TF_GRID)] = window
        bot.data_engine.data[(symbol, config.TF_TREND)] = window

        # Async iterate loops
        await bot.iterate(target_symbol=symbol)

    # Extract PAPER metrics logically via its own isolation
    final_price = float(df.iloc[-1]["close"])
    live_equity, _ = await bot.execution_router.get_equity_and_pnl(
        {symbol: final_price}
    )
    live_pnl = live_equity - 10000.0  # Assumes 10k starting

    paper_metrics = bot.execution_router.get_state_metrics()
    live_trades = paper_metrics.get("history", [])

    # ====================================================
    # 3. COMPARE AND ASSERT PARITY (Symmetry Tests)
    # ====================================================
    print(
        f"\n>>>> BT SIGNALS: {bt_signals_count} | LIVE SIGNALS: {live_signals_count} <<<<"
    )
    print(f">>>> BT PnL: {bt_pnl:,.2f} | LIVE PnL: {live_pnl:,.2f} <<<<")

    # We must have generated active validation signals
    assert bt_signals_count > 0, "No backtest signals generated to validate."

    # Signals must match almost identically natively across both isolated architectures
    signal_diff = abs(bt_signals_count - live_signals_count)
    assert (
        signal_diff <= 2
    ), f"Logic Parity FAILED! Backtest generated {bt_signals_count} signals vs BotRunner {live_signals_count}. Discrepancy proves environment logic mismatch."

    # PnL difference must be constrained explicitly to realistic bounds
    pnl_diff = abs(bt_pnl - live_pnl)
    assert (
        pnl_diff < 500.0
    ), f"PnL validation mismatch! Difference too massive ({pnl_diff}), simulated architectures broken."
