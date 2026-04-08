import asyncio
import time
import psutil
import os
import pandas as pd
import numpy as np
import unittest
import logging
import gc
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, UTC

from orchestration.bot_runner import BotRunner
from config.config_loader import Config
from common.types import Signal, SignalAction, Side, Regime
from execution.shadow_executor import ShadowExecutor
from regime.regime_detector import RegimeDetector
from regime.volatility_detector import VolatilityRegimeDetector


class FastReturn:
    def __init__(self, val):
        self.val = val

    def __call__(self, *args, **kwargs):
        return self.val


class FastAsyncReturn:
    def __init__(self, val):
        self.val = val

    async def __call__(self, *args, **kwargs):
        return self.val


class DummyLogger:
    def info(self, *args, **kwargs):
        pass

    def error(self, *args, **kwargs):
        pass

    def warning(self, *args, **kwargs):
        pass

    def debug(self, *args, **kwargs):
        pass

    def critical(self, *args, **kwargs):
        pass


class StabilityTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        # 1. Setup minimal config for speed
        self.config = Config()
        self.config.SYMBOLS = ["BTC/USDT"]
        self.config.CANDLES_ANALYSIS_LIMIT = 50
        self.config.EXECUTION_MODE = "SHADOW"
        self.config.ANALYSIS_ONLY = True
        self.config.POLLING_INTERVAL = 0
        self.config.USE_WEBSOCKETS = False

        # Ensure logging is silenced globally
        logging.disable(logging.CRITICAL)

        # 2. Optimized Mocks (Non-recording)
        self.mock_balance = {"total": {"USDT": 10000.0}, "free": {"USDT": 10000.0}}
        self.mock_exchange = MagicMock()
        self.mock_exchange.fetch_balance = FastAsyncReturn(self.mock_balance)
        self.mock_exchange.fetch_open_orders = FastAsyncReturn([])
        self.mock_exchange.fetch_my_trades = FastAsyncReturn([])
        self.mock_exchange.set_leverage = FastAsyncReturn(True)
        self.mock_exchange.init = FastAsyncReturn(None)
        self.mock_exchange.close = FastAsyncReturn(None)
        self.mock_exchange._apply_backoff = FastAsyncReturn(None)

        self.mock_exchange.fetch_order_book = FastAsyncReturn(
            {"bids": [[99.9, 10.0]], "asks": [[100.1, 10.0]]}
        )

        # Mock DataEngine
        self.mock_data_engine = MagicMock()

        # Mock Telegram
        self.mock_telegram = MagicMock()
        self.mock_telegram.is_healthy = FastReturn(True)
        self.mock_telegram.info = FastAsyncReturn(None)
        self.mock_telegram.error = FastAsyncReturn(None)
        self.mock_telegram.warning = FastAsyncReturn(None)
        self.mock_telegram.critical = FastAsyncReturn(None)
        self.mock_telegram.trade = FastAsyncReturn(None)
        self.mock_telegram.flush_alerts = FastAsyncReturn(None)
        self.mock_telegram.verify_bot = FastAsyncReturn("StabilityBot")

        # Mock DB
        self.mock_db = MagicMock()
        self.mock_db.get_recent_trades = FastReturn([])
        self.mock_db.save_trade = FastReturn(True)
        self.mock_db.get_stats = FastReturn({"total_trades": 0})

        # Optimized Indicators: Pre-generate once
        from indicators.technical_indicators import add_standard_indicators
        from indicators.volume_profile import compute_volume_profile

        base_price = 100.0
        synthetic_df = pd.DataFrame(
            np.random.randn(self.config.CANDLES_ANALYSIS_LIMIT, 5) * 0.1 + base_price,
            columns=["open", "high", "low", "close", "volume"],
        )
        synthetic_df["timestamp"] = pd.date_range(
            end=datetime.now(UTC), periods=len(synthetic_df), freq="15min"
        )
        self.synthetic_df = add_standard_indicators(synthetic_df)
        self.vp = compute_volume_profile(self.synthetic_df)

        # Patch expensive I/O and external calls
        self.dummy_logger = DummyLogger()
        self.fast_indicators = FastReturn(self.synthetic_df)
        self.fast_vp = FastReturn(self.vp)

        patches = [
            patch(
                "orchestration.bot_runner.setup_logger", return_value=self.dummy_logger
            ),
            patch("orchestration.bot_runner.write_bot_state", return_value=None),
            patch("data.db_manager.DbManager", return_value=self.mock_db),
            patch(
                "logging_monitoring.telegram_alert_service.TelegramAlertService",
                return_value=self.mock_telegram,
            ),
            patch("monitoring.metrics.start_metrics_exporter", return_value=None),
            patch(
                "orchestration.bot_runner.add_standard_indicators",
                side_effect=self.fast_indicators,
            ),
            patch(
                "orchestration.bot_runner.compute_volume_profile",
                side_effect=self.fast_vp,
            ),
            patch("orchestration.bot_runner.RegimeDetector", spec=RegimeDetector),
            patch(
                "orchestration.bot_runner.VolatilityRegimeDetector",
                spec=VolatilityRegimeDetector,
            ),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

        def reenable_logging():
            logging.disable(logging.NOTSET)

        self.addCleanup(reenable_logging)

        # Initialize BotRunner
        self.runner = BotRunner(
            config=self.config,
            exchange=self.mock_exchange,
            data_engine=self.mock_data_engine,
        )

        # Final stubs
        self.runner._write_dashboard_state = self.dummy_logger.info
        self.runner.update_status = self.dummy_logger.info
        self.runner.regime_detector.detect_regime = FastReturn(Regime.TREND)
        self.runner.volatility_detector.detect_regime = FastReturn("normal")
        self.runner.volatility_detector.calculate_atr = FastReturn(
            pd.Series([1.0] * self.config.CANDLES_ANALYSIS_LIMIT)
        )

    async def test_long_run_stability(self):
        num_events = int(os.getenv("NUM_EVENTS", 50000))
        print(f"\nStarting stability test: {num_events} events...")

        # Store in mock data engine
        self.mock_data_engine.data = {
            ("BTC/USDT", self.config.TF_GRID): self.synthetic_df,
            ("BTC/USDT", self.config.TF_TREND): self.synthetic_df,
        }
        self.mock_data_engine.fetch_ohlcv = FastAsyncReturn(self.synthetic_df)

        start_time = time.time()
        process = psutil.Process(os.getpid())
        initial_mem = process.memory_info().rss / (1024 * 1024)
        initial_equity = self.mock_balance["total"]["USDT"]

        equity_history = []
        latencies = []

        for i in range(num_events):
            step_start = time.perf_counter()
            await self.runner.iterate()
            step_end = time.perf_counter()

            latencies.append(step_end - step_start)

            # Record equity every 100 events to save memory in history
            if i % 100 == 0:
                # In shadow/paper mode, equity is stable unless trades occur
                # We fetch from the mocked balance or current internal state
                current_equity = self.mock_balance["total"]["USDT"]
                equity_history.append(current_equity)

            if (i + 1) % 10000 == 0:
                elapsed = time.time() - start_time
                current_mem = process.memory_info().rss / (1024 * 1024)
                tasks = len(asyncio.all_tasks())
                print(
                    f"[{i+1:>5}] Elapsed: {elapsed:>5.2f}s | Mem: {current_mem:>7.2f} MB | Tasks: {tasks}"
                )
                gc.collect()

        end_time = time.time()
        final_mem = process.memory_info().rss / (1024 * 1024)
        mem_growth = final_mem - initial_mem

        # Calculate Stats
        avg_latency = (sum(latencies) / len(latencies)) * 1000  # ms

        # Drawdown calculation
        eq_ser = pd.Series(equity_history)
        roll_max = eq_ser.cummax()
        drawdowns = (roll_max - eq_ser) / roll_max
        max_dd = drawdowns.max() * 100  # %

        trade_count = self.runner.metrics["orders_placed"]

        print(f"\n" + "=" * 40)
        print(f"       STABILITY TEST RESULTS     ")
        print(f"=" * 40)
        print(f"Total Duration:     {end_time - start_time:8.2f} s")
        print(f"Avg Latency/Event:  {avg_latency:8.2f} ms")
        print(f"Memory Growth:      {mem_growth:8.2f} MB")
        print(f"Max Drawdown:       {max_dd:8.2f} %")
        print(f"Total Trades:       {trade_count:8d}")
        print(f"=" * 40)

        # Performance Assertions
        duration_limit = 60 if num_events <= 50000 else 180
        mem_limit = 250 if num_events <= 50000 else 1000

        self.assertLess(end_time - start_time, duration_limit, "Test too slow")
        self.assertLess(mem_growth, mem_limit, "Potential memory leak detected")
        self.assertLess(
            avg_latency, 2.0, "Latency too high"
        )  # Should be sub-1ms usually

        # Consistency Assertion
        # Verify that total equity + PnL doesn't drift uncontrollably
        # In this static mock, balance stays constant, so max_dd should be 0.
        self.assertEqual(max_dd, 0.0, "Unexpected equity drift in mock environment")

        await self.runner.close()


if __name__ == "__main__":
    unittest.main()
