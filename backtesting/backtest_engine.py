"""
Core backtesting engine.
Replays historical candles through the existing strategy pipeline.
"""

import asyncio
import logging
import pandas as pd
from typing import Optional

from config.config_loader import Config
from indicators.technical_indicators import add_standard_indicators
from indicators.volume_profile import compute_volume_profile
from regime.regime_detector import RegimeDetector
from strategy.neutral_grid_strategy import NeutralGridStrategy
from strategy.trend_dca_strategy import TrendDcaStrategy
from strategy.strategy_router import StrategyRouter
from risk.risk_manager import RiskManager
from backtesting.sim_broker import SimBroker
from backtesting.metrics import calculate_metrics, BacktestMetrics
from common.types import SignalAction

logger = logging.getLogger(__name__)


def _run_async(coro):
    """Run an async coroutine from synchronous code."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # If inside an existing loop, create a new one in a thread
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor() as pool:
                return pool.submit(asyncio.run, coro).result()
        return loop.run_until_complete(coro)
    except RuntimeError:
        return asyncio.run(coro)


# Timeframe to approximate candles-per-day
TF_TO_CPD = {
    "1m": 1440,
    "3m": 480,
    "5m": 288,
    "15m": 96,
    "30m": 48,
    "1h": 24,
    "2h": 12,
    "4h": 6,
    "6h": 4,
    "8h": 3,
    "12h": 2,
    "1d": 1,
}


class BacktestEngine:
    """
    Replays historical OHLCV data through the bot's strategy pipeline.

    Reuses without modification:
    - add_standard_indicators
    - compute_volume_profile
    - RegimeDetector
    - NeutralGridStrategy / TrendDcaStrategy
    - StrategyRouter
    - RiskManager.calculate_position_size
    """

    def __init__(
        self,
        symbol: str = "BTC/USDT",
        timeframe: str = "4h",
        initial_balance: float = 10000.0,
        maker_fee: float = 0.0004,
        taker_fee: float = 0.0006,
        slippage: float = 0.0001,
        lookback: int = 250,
    ):
        self.symbol = symbol
        self.timeframe = timeframe
        self.lookback = lookback

        # Config (reuse existing)
        self.config = Config()
        self.config.ANALYSIS_ONLY = True  # Safety

        # Modules (same as BotRunner)
        self.regime_detector = RegimeDetector()
        self.grid_strategy = NeutralGridStrategy(self.config)
        self.trend_strategy = TrendDcaStrategy(self.config)
        self.router = StrategyRouter(self.grid_strategy, self.trend_strategy)
        self.risk_manager = RiskManager(self.config)

        # Simulated broker (replaces ExchangeClient + PaperManager)
        self.broker = SimBroker(
            initial_balance=initial_balance,
            maker_fee=maker_fee,
            taker_fee=taker_fee,
            slippage=slippage,
        )

    def run(self, df: pd.DataFrame) -> BacktestMetrics:
        """
        Run the backtest on a DataFrame of historical OHLCV data.

        Args:
            df: DataFrame with columns [timestamp, open, high, low, close, volume]

        Returns:
            BacktestMetrics with all calculated performance metrics
        """
        logger.info(
            f"Starting backtest: {self.symbol} | {len(df)} candles | "
            f"Balance: ${self.broker.initial_balance:,.0f}"
        )

        total_candles = len(df)
        start_idx = self.lookback
        signals_generated = 0

        if start_idx >= total_candles:
            logger.error(
                f"Not enough candles ({total_candles}) for lookback ({self.lookback})"
            )
            return self._empty_metrics(df)

        # Record initial equity
        self.broker.equity_curve.append(self.broker.balance)

        for i in range(start_idx, total_candles):
            # Sliding window for indicators
            window = df.iloc[max(0, i - self.lookback) : i + 1].copy()

            # Current candle data
            candle = df.iloc[i]
            current_price = float(candle["close"])

            # 1. Add indicators
            window = add_standard_indicators(window)

            # 2. Volume Profile
            vp = compute_volume_profile(window)

            # 3. Regime Detection
            regime = self.regime_detector.detect_regime(window)

            # 4. Build market state (same format as BotRunner)
            position = self.broker.get_position_dict(self.symbol)
            equity = self.broker.get_equity_with_unrealized(
                {self.symbol: current_price}
            )

            market_state = {
                "price": current_price,
                "df": window,
                "volume_profile": vp,
                "equity": equity,
                "position": position if position else None,
            }

            # 5. Route signals (async → run in sync context)
            signals = _run_async(
                self.router.route_signals(self.symbol, regime, market_state)
            )

            # 6. Process signals through broker
            for signal in signals:
                if not signal.price:
                    continue

                # Calculate position size if missing
                if not signal.amount:
                    signal.amount = self.risk_manager.calculate_position_size(
                        self.symbol, signal.price, signal.stop_loss, equity
                    )

                self.broker.process_signal(signal, current_price, candle_idx=i)
                signals_generated += 1

            # 7. Update broker (check pending orders, SL/TP)
            self.broker.update_on_candle(
                {
                    "symbol": self.symbol,
                    "open": float(candle["open"]),
                    "high": float(candle["high"]),
                    "low": float(candle["low"]),
                    "close": current_price,
                },
                candle_idx=i,
            )

            # 8. Record equity
            eq = self.broker.get_equity_with_unrealized({self.symbol: current_price})
            self.broker.equity_curve.append(eq)

            # Progress log every 10%
            progress = (i - start_idx) / (total_candles - start_idx)
            if (
                i == start_idx
                or (i - start_idx) % max(1, (total_candles - start_idx) // 10) == 0
            ):
                logger.info(
                    f"  [{progress * 100:5.1f}%] Candle {i}/{total_candles} | "
                    f"Price: {current_price:,.2f} | Regime: {regime} | "
                    f"Equity: ${eq:,.2f} | Trades: {len(self.broker.trades)}"
                )

        # Force close remaining positions at last price
        last_price = float(df.iloc[-1]["close"])
        self.broker.force_close_all(
            {self.symbol: last_price}, candle_idx=total_candles - 1
        )

        # Final equity after closing
        final_eq = self.broker.balance
        self.broker.equity_curve[-1] = final_eq

        logger.info(
            f"Backtest complete. {signals_generated} signals, {len(self.broker.trades)} trades."
        )

        # Calculate metrics
        buy_hold_start = float(df.iloc[start_idx]["close"])
        buy_hold_end = float(df.iloc[-1]["close"])
        cpd = TF_TO_CPD.get(self.timeframe, 6)

        metrics = calculate_metrics(
            equity_curve=self.broker.equity_curve,
            trades=self.broker.trades,
            initial_equity=self.broker.initial_balance,
            buy_hold_start_price=buy_hold_start,
            buy_hold_end_price=buy_hold_end,
            candles_per_day=cpd,
        )

        return metrics

    def _empty_metrics(self, df) -> BacktestMetrics:
        """Return empty metrics when backtest can't run."""
        return BacktestMetrics(
            total_return_pct=0,
            total_pnl=0,
            sharpe_ratio=0,
            max_drawdown_pct=0,
            max_drawdown_abs=0,
            win_rate=0,
            profit_factor=0,
            total_trades=0,
            winning_trades=0,
            losing_trades=0,
            avg_trade_pnl=0,
            avg_winner=0,
            avg_loser=0,
            max_consecutive_losses=0,
            calmar_ratio=0,
            buy_and_hold_return_pct=0,
            initial_equity=self.broker.initial_balance,
            final_equity=self.broker.initial_balance,
            peak_equity=self.broker.initial_balance,
        )
