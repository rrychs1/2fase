import asyncio
import time
import pandas as pd
import numpy as np
import unittest
import logging
from unittest.mock import MagicMock, patch
from datetime import datetime, UTC

from orchestration.bot_runner import BotRunner
from config.config_loader import Config
from common.types import Regime

class FastReturn:
    def __init__(self, val): self.val = val
    def __call__(self, *args, **kwargs): return self.val

class FastAsyncReturn:
    def __init__(self, val): self.val = val
    async def __call__(self, *args, **kwargs): return self.val

class DummyLogger:
    def info(self, *args, **kwargs): pass
    def error(self, *args, **kwargs): pass
    def warning(self, *args, **kwargs): pass
    def debug(self, *args, **kwargs): pass
    def critical(self, *args, **kwargs): pass

class DeterministicReplayTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        # Silence logging for clean output
        logging.disable(logging.CRITICAL)
        
    def tearDown(self):
        logging.disable(logging.NOTSET)

    def generate_deterministic_data(self, seed=42, n_points=100):
        """Generate a reproducible OHLCV dataset."""
        np.random.seed(seed)
        base_price = 100.0
        
        # Random walk for price
        returns = np.random.normal(0, 0.01, n_points)
        prices = base_price * (1 + returns).cumprod()
        
        df = pd.DataFrame({
            'timestamp': pd.date_range(end=datetime.now(UTC), periods=n_points, freq='15min'),
            'open': prices * (1 + np.random.normal(0, 0.001, n_points)),
            'high': prices * (1 + np.abs(np.random.normal(0, 0.002, n_points))),
            'low': prices * (1 - np.abs(np.random.normal(0, 0.002, n_points))),
            'close': prices,
            'volume': np.random.uniform(10, 100, n_points)
        })
        return df

    async def run_simulation(self, dataset):
        """Run the full bot pipeline and record all outputs."""
        config = Config()
        config.SYMBOLS = ["BTC/USDT"]
        config.CANDLES_ANALYSIS_LIMIT = 50
        config.EXECUTION_MODE = 'SHADOW'
        config.ANALYSIS_ONLY = True
        config.POLLING_INTERVAL = 0
        config.USE_WEBSOCKETS = False
        
        # Mocks
        mock_balance = {'total': {'USDT': 10000.0}, 'free': {'USDT': 10000.0}}
        mock_exchange = MagicMock()
        mock_exchange.fetch_balance = FastAsyncReturn(mock_balance)
        mock_exchange.fetch_open_orders = FastAsyncReturn([])
        mock_exchange.fetch_my_trades = FastAsyncReturn([])
        mock_exchange.set_leverage = FastAsyncReturn(True)
        mock_exchange.init = FastAsyncReturn(None)
        mock_exchange.close = FastAsyncReturn(None)
        mock_exchange.fetch_order_book = FastAsyncReturn({
            'bids': [[dataset['close'].iloc[-1]*0.999, 10.0]], 
            'asks': [[dataset['close'].iloc[-1]*1.001, 10.0]]
        })
        
        mock_data_engine = MagicMock()
        # In this simulation, we'll feed data manually to ensure determinism
        
        # Recording storage
        trades_recorded = []
        equity_curve = []
        
        # Capture metrics server updates to prevent side effects
        with patch('orchestration.bot_runner.setup_logger', return_value=DummyLogger()), \
             patch('orchestration.bot_runner.write_bot_state', return_value=None), \
             patch('data.db_manager.DbManager') as mock_db_class, \
             patch('logging_monitoring.telegram_alert_service.TelegramAlertService'), \
             patch('logging_monitoring.metrics_server.start_metrics_exporter'):
            
            mock_db = mock_db_class.return_value
            # Record every call to save_trade
            def save_trade_recorder(trade):
                trades_recorded.append(trade)
                return True
            mock_db.save_trade.side_effect = save_trade_recorder
            
            runner = BotRunner(config=config, exchange=mock_exchange, data_engine=mock_data_engine)
            # Ensure it uses our fixed dataset
            mock_data_engine.data = {
                ("BTC/USDT", config.TF_GRID): dataset,
                ("BTC/USDT", config.TF_TREND): dataset
            }
            mock_data_engine.fetch_ohlcv = FastAsyncReturn(dataset)
            
            # Static indicators for speed/determinism
            from indicators.technical_indicators import add_standard_indicators
            from indicators.volume_profile import compute_volume_profile
            processed_df = add_standard_indicators(dataset)
            vp = compute_volume_profile(processed_df)
            
            with patch('orchestration.bot_runner.add_standard_indicators', return_value=processed_df), \
                 patch('orchestration.bot_runner.compute_volume_profile', return_value=vp):
                
                # Force specific regime for consistent signal paths (or let it detect)
                # We'll let it detect from the seed-generated data
                
                # Run 5 iterations
                for _ in range(5):
                    await runner.iterate()
                    # Reconstruct current_prices for equity calculation
                    current_prices = {s: dataset['close'].iloc[-1] for s in config.SYMBOLS}
                    eq, _ = await runner.execution_router.get_equity_and_pnl(current_prices)
                    equity_curve.append(eq)

            final_state = {
                'positions': runner.current_positions.copy(),
                'balance': mock_balance['total']['USDT'],
                'metrics': runner.metrics.copy(),
                'equity': equity_curve[-1]
            }
            
            await runner.close()
            
        return trades_recorded, equity_curve, final_state

    async def test_deterministic_replay(self):
        """Verify that two identical runs produce identical results."""
        dataset = self.generate_deterministic_data(seed=123, n_points=60)
        
        print("\nPass 1: Executing simulation...")
        trades1, equity1, state1 = await self.run_simulation(dataset)
        
        print("Pass 2: Executing identical simulation...")
        trades2, equity2, state2 = await self.run_simulation(dataset)
        
        # 1. Compare Trades
        self.assertEqual(len(trades1), len(trades2), "Trade count mismatch!")
        for t1, t2 in zip(trades1, trades2):
            # Check key fields (ignore potential dynamic fields like timestamps if they are real-time)
            # But since we mock everything, even timestamps in trades should ideally be derived from data
            self.assertEqual(t1['symbol'], t2['symbol'])
            self.assertEqual(t1['side'], t2['side'])
            self.assertEqual(t1['price'], t2['price'])
            self.assertEqual(t1['amount'], t2['amount'])
            
        # 2. Compare Equity Curves
        self.assertEqual(equity1, equity2, "Equity curves diverged!")
        
        # 3. Compare Final States
        self.assertEqual(state1['balance'], state2['balance'], "Final balance mismatch!")
        self.assertEqual(state1['metrics'], state2['metrics'], "Metrics mismatch!")
        self.assertEqual(state1['positions'], state2['positions'], "Positions mismatch!")
        
        print("\n[SUCCESS] Deterministic replay verified: Pass 1 == Pass 2 (Exact match)")

if __name__ == "__main__":
    unittest.main()
