import asyncio
import time
import json
import os
from datetime import datetime
import logging
from config.config_loader import Config
from exchange.exchange_client import ExchangeClient
from data.data_engine import DataEngine
from indicators.technical_indicators import add_standard_indicators
from indicators.volume_profile import compute_volume_profile
from regime.regime_detector import RegimeDetector
from strategy.neutral_grid_strategy import NeutralGridStrategy
from strategy.trend_dca_strategy import TrendDcaStrategy
from strategy.strategy_router import StrategyRouter
from risk.risk_manager import RiskManager
from execution.execution_engine import ExecutionEngine
from execution.paper_manager import PaperManager
from common.types import Side, SignalAction
from logging_monitoring.logger import setup_logger

logger = setup_logger()

from execution.paper_manager import PaperManager

class BotRunner:
    def __init__(self):
        self.start_time = datetime.now()
        self.config = Config()
        self.exchange = ExchangeClient()
        self.data_engine = DataEngine(self.exchange)
        self.regime_detector = RegimeDetector()
        
        self.neutral_grid = NeutralGridStrategy(self.config)
        self.trend_dca = TrendDcaStrategy(self.config)
        self.router = StrategyRouter(self.neutral_grid, self.trend_dca)
        
        self.risk_manager = RiskManager(self.config)
        self.execution = ExecutionEngine(self.exchange, self.config)
        self.paper_manager = PaperManager()
        self.update_status("Initialized")

    async def run(self):
        logger.info("Starting Async Bot Runner (Paper & Analytics Mode)...")
        await self.exchange.init()
        
        if not self.config.ANALYSIS_ONLY:
            for symbol in self.config.SYMBOLS:
                await self.exchange.set_leverage(symbol, self.config.LEVERAGE)

        try:
            while True:
                start_iter = time.time()
                try:
                    await self.iterate()
                except Exception as e:
                    logger.error(f"Error in iteration: {e}", exc_info=True)
                
                elapsed = time.time() - start_iter
                sleep_time = max(1, self.config.POLLING_INTERVAL - elapsed)
                await asyncio.sleep(sleep_time)
        finally:
            await self.exchange.close()

    async def iterate(self):
        logger.info("--- Starting Iteration ---")
        self.update_status("Running")
        
        current_prices = {}
        # 0. Fetch latest prices for all symbols first to accurately estimate equity/risk
        for symbol in self.config.SYMBOLS:
            df_4h = await self.data_engine.fetch_ohlcv(symbol, self.config.TF_GRID)
            if df_4h is not None and len(df_4h) > 0:
                current_prices[symbol] = df_4h.iloc[-1]['close']

        # 1. Sync Account State with accurate prices
        try:
            if self.config.ANALYSIS_ONLY:
                equity = self.paper_manager.get_equity(current_prices)
                unrealized_pnl = equity - self.paper_manager.state["balance"]
            else:
                balance = await self.exchange.fetch_balance()
                equity = float(balance.get('total', {}).get('USDT', 0.0))
                unrealized_pnl = await self.execution.get_account_pnl()
            
            # 2. Global Risk Check (Kill Switch)
            if self.risk_manager.check_daily_drawdown(unrealized_pnl, equity):
                logger.critical("KILL SWITCH: Closing all positions!")
                if self.config.ANALYSIS_ONLY:
                    self.paper_manager.state["positions"] = {}
                    self.paper_manager.state["pending_orders"] = []
                else:
                    await self.execution.close_all_positions()
                return
        except Exception as e:
            logger.warning(f"Failed to sync account state: {e}")
            equity = 10000.0 if self.config.ANALYSIS_ONLY else 0.0
            unrealized_pnl = 0.0

        for symbol in self.config.SYMBOLS:
            # 3. Update Data & Indicators
            df_4h = await self.data_engine.fetch_ohlcv(symbol, self.config.TF_GRID)
            df_trend = await self.data_engine.fetch_ohlcv(symbol, self.config.TF_TREND)
            
            if df_4h is None or df_trend is None or len(df_4h) < 20: continue
            
            price = current_prices.get(symbol, df_4h.iloc[-1]['close'])
            
            # Update Paper Positions (Check SL/TP and Pending Orders)
            if self.config.ANALYSIS_ONLY:
                self.paper_manager.update_positions({symbol: price})

            df_4h = add_standard_indicators(df_4h)
            df_trend = add_standard_indicators(df_trend)
            vp = compute_volume_profile(df_4h)
            
            regime = self.regime_detector.detect_regime(df_4h)

            # 4. Strategy Analysis
            if self.config.ANALYSIS_ONLY:
                position = self.paper_manager.state["positions"].get(symbol, {})
            else:
                position = await self.execution.get_position(symbol)

            # Concise Symbol Summary
            pos_info = "None"
            if position:
                pos_info = f"{position['side']} {position['amount']:.4f}"
            
            logger.info(f"[{symbol}] Price: {price:.2f} | Regime: {regime.upper()} | Pos: {pos_info}")

            market_state = {
                'price': price,
                'df': df_trend,
                'volume_profile': vp,
                'equity': equity,
                'position': position
            }
            signals = await self.router.route_signals(symbol, regime, market_state)
            
            # 5. Execution Logic
            for signal in signals:
                if not signal.price: continue
                
                # Enrich signal with amount if missing
                if not signal.amount:
                    signal.amount = self.risk_manager.calculate_position_size(
                        symbol, signal.price, signal.stop_loss, equity
                    )
                
                if self.config.ANALYSIS_ONLY:
                    self.paper_manager.execute_signal(signal)
                else:
                    # LIVE EXECUTION
                    if signal.action == SignalAction.GRID_PLACE:
                        # Place Limit Order
                        yield_order = await self.execution.place_order(
                            symbol, signal.side.value.lower(), 'limit', signal.amount, signal.price
                        )
                        if yield_order:
                            logger.info(f"[LIVE] Grid Limit Order: {signal.side} @ {signal.price}")

                    elif signal.action in [SignalAction.ENTER_LONG, SignalAction.ENTER_SHORT]:
                        # 1. Market Entry
                        order = await self.execution.place_order(
                            symbol, signal.side.value.lower(), 'market', signal.amount
                        )
                        if order:
                            logger.info(f"[LIVE] Market Entry Executed: {order.get('id')}")
                            
                            # 2. Place SL (Stop Market)
                            if signal.stop_loss:
                                sl_side = 'sell' if signal.side == Side.LONG else 'buy'
                                await self.execution.place_order(
                                    symbol, sl_side, 'stop', signal.amount, signal.stop_loss,
                                    params={'stopPrice': signal.stop_loss, 'reduceOnly': True}
                                )
                                logger.info(f"[LIVE] Stop Loss Placed @ {signal.stop_loss}")
                            
                            # 3. Place TP (Limit)
                            if signal.take_profit:
                                tp_side = 'sell' if signal.side == Side.LONG else 'buy'
                                await self.execution.place_order(
                                    symbol, tp_side, 'limit', signal.amount, signal.take_profit,
                                    params={'reduceOnly': True}
                                )
                                logger.info(f"[LIVE] Take Profit Placed @ {signal.take_profit}")

                    elif signal.action in [SignalAction.EXIT_LONG, SignalAction.EXIT_SHORT]:
                        # Close Position
                        await self.execution.place_order(
                            symbol, signal.side.value.lower() == 'long' and 'sell' or 'buy', 'market', signal.amount,
                            params={'reduceOnly': True}
                        )
                        logger.info(f"[LIVE] Position Closed: {symbol}")
            
            # Paper Trading Logging
            self._append_paper_record(
                symbol=symbol,
                price=price,
                regime=regime,
                signals_count=len(signals),
                virtual_equity=self.paper_manager.get_equity(current_prices)
            )

    def update_status(self, status):
        uptime = str(datetime.now() - self.start_time).split(".")[0]
        status_data = {
            "status": status, "uptime": uptime,
            "mode": "Paper" if self.config.USE_TESTNET else "Live",
            "last_loop": datetime.now().isoformat()
        }
        with open("status.json", "w") as f: json.dump(status_data, f, indent=4)

    def _append_paper_record(self, **kwargs):
        record = {'ts': datetime.utcnow().isoformat(), **kwargs}
        with open('papers.jsonl', 'a') as f: f.write(json.dumps(record) + "\n")

if __name__ == "__main__":
    runner = BotRunner()
    asyncio.run(runner.run())
