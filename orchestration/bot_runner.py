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
from logging_monitoring.telegram_bot import TelegramBot

logger = setup_logger()

class BotRunner:
    def __init__(self, config=None, exchange=None, risk_manager=None, data_engine=None):
        from data.db_manager import DbManager
        
        self.start_time = datetime.now()
        self.config = config or Config()
        self.exchange = exchange or ExchangeClient()
        self.data_engine = data_engine or DataEngine(self.exchange)
        self.regime_detector = RegimeDetector()
        self.db = DbManager() # Senior Audit Phase 4
        
        self.neutral_grid = NeutralGridStrategy(self.config)
        self.trend_dca = TrendDcaStrategy(self.config)
        self.router = StrategyRouter(self.neutral_grid, self.trend_dca)
        
        self.risk_manager = RiskManager(self.config)
        self.execution = ExecutionEngine(self.exchange, self.config)
        self.paper_manager = PaperManager()
        self.telegram = TelegramBot()
        self.last_grid_update = {}
        self.iteration_count = 0
        self.trades_today = 0
        self.last_summary_time = 0
        # Dashboard state tracking
        self.current_regimes = {}
        self.current_prices = {}
        self.current_positions = {}
        self.current_orders = []
        self.current_history = []
        self.update_status("Initialized")

    async def run(self):
        mode_str = "SIM" if self.config.TRADING_ENV == 'SIM' else ("Analysis Only (Paper)" if self.config.ANALYSIS_ONLY else ("Testnet" if self.config.USE_TESTNET else "LIVE"))
        logger.info(f"Starting Async Bot Runner [Mode: {mode_str}]...")
        
        bot_username = await self.telegram.verify_bot()
        startup_msg = f"🤖 **Bot Iniciado** (@{bot_username})\nModo: " + ("Testnet" if self.config.USE_TESTNET else "LIVE")
        logger.info(f"Risk Hierarchy: Kill Switch -> Safe Mode -> Daily Loss -> Cooldown")
        await self.telegram.send_message(startup_msg)
        
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
                    error_msg = f"Error in iteration: {e}"
                    logger.error(error_msg, exc_info=True)
                    await self.telegram.send_error_alert(error_msg)
                
                elapsed = time.time() - start_iter
                logger.info(f"Cycle processed | symbols={len(self.config.SYMBOLS)} duration={elapsed*1000:.0f}ms")
                
                sleep_time = max(1, self.config.POLLING_INTERVAL - elapsed)
                await asyncio.sleep(sleep_time)
        finally:
            await self.telegram.send_message("🛑 **Bot Detenido**")
            await self.exchange.close()

    async def iterate(self):
        self.iteration_count += 1
        # Silent start, only log summary at the end
        self.update_status("Running")
        
        current_prices = {}
        self.current_regimes = {}
        self.current_positions = {}
        self.current_orders = []
        self.current_history = []
        # 0. Fetch latest prices for all symbols first to accurately estimate equity/risk
        for symbol in self.config.SYMBOLS:
            df_4h = await self.data_engine.fetch_ohlcv(symbol, self.config.TF_GRID, limit=self.config.CANDLES_ANALYSIS_LIMIT)
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
            
            # Sync reference equity for the entire cycle
            drift_alert, drift_val = self.risk_manager.sync_reference_equity(equity, unrealized_pnl)
            if drift_alert:
                alert_msg = (f"⚠️ **ALERTA DE SEGURIDAD: Deriva de Equity**\n"
                             f"Se ha detectado un cambio inexplicable de {drift_val*100:.2f}%\n"
                             f"**Modo Seguro ACTIVADO**. Se bloquean nuevas entradas.")
                await self.telegram.send_error_alert(alert_msg)
            
            # 2. Periodic Reconciliation (Senior Audit Phase 3)
            # Revalidar estado real vs memoria cada N iteraciones
            if self.risk_manager.needs_reconciliation(self.iteration_count):
                logger.info(f"[Bot] Starting Periodic Reconciliation (Iteration {self.iteration_count})")
                for s_symbol in self.config.SYMBOLS:
                    open_orders = await self.exchange.fetch_open_orders(s_symbol)
                    self.neutral_grid.reconcile_with_exchange(s_symbol, open_orders)
                    self.trend_dca.reconcile_with_exchange(s_symbol, open_orders)

            # 3. Global Risk Check (Kill Switch)
            if self.risk_manager.check_daily_drawdown(unrealized_pnl, equity):
                msg = "KILL SWITCH: Closing all positions!"
                logger.critical(msg)
                await self.telegram.send_error_alert(msg)
                
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
            df_4h = await self.data_engine.fetch_ohlcv(symbol, self.config.TF_GRID, limit=self.config.CANDLES_ANALYSIS_LIMIT)
            df_trend = await self.data_engine.fetch_ohlcv(symbol, self.config.TF_TREND, limit=self.config.CANDLES_ANALYSIS_LIMIT)
            
            if df_4h is None or df_trend is None or len(df_4h) < 20: continue
            
            price = current_prices.get(symbol, df_4h.iloc[-1]['close'])
            
            # Update Paper Positions (Check SL/TP and Pending Orders)
            if self.config.ANALYSIS_ONLY:
                self.paper_manager.update_positions({symbol: price})

            df_4h = add_standard_indicators(df_4h)
            df_trend = add_standard_indicators(df_trend)
            vp = compute_volume_profile(df_4h)
            
            # 3. Transition Tolerance (Phase 3)
            # If regime changed, reconcile immediately to avoid orphan orders
            old_regime = self.current_regimes.get(symbol)
            regime = self.regime_detector.detect_regime(df_4h)
            
            if old_regime and old_regime != regime:
                logger.warning(f"[{symbol}] REGIME CHANGE DETECTED: {old_regime} -> {regime}. Immediate reconciliation starting...")
                trans_orders = await self.exchange.fetch_open_orders(symbol)
                # Ensure strategies see the current orders before routing signals
                self.neutral_grid.reconcile_with_exchange(symbol, trans_orders)
                self.trend_dca.reconcile_with_exchange(symbol, trans_orders)
            
            self.current_regimes[symbol] = regime

            # 4. Strategy Analysis
            if self.config.ANALYSIS_ONLY:
                position = self.paper_manager.state["positions"].get(symbol, {})
            else:
                position = await self.execution.get_position(symbol)

            # Track position for dashboard
            if position:
                self.current_positions[symbol] = position

            # Concise Symbol Summary
            pos_info = "None"
            if position:
                pos_info = f"{position.get('side', '')} {float(position.get('amount', 0)):.4f}"
            
            logger.debug(f"[{symbol}] Price: {price:.2f} | Regime: {regime.upper()} | Pos: {pos_info}")

            market_state = {
                'price': price,
                'df': df_trend,
                'volume_profile': vp,
                'equity': equity,
                'position': position
            }
            signals = await self.router.route_signals(symbol, regime, market_state)
            
            # Track Orders and History in Live Mode
            if not self.config.ANALYSIS_ONLY:
                symbol_orders = await self.exchange.fetch_open_orders(symbol)
                self.current_orders.extend(symbol_orders)
                
                symbol_trades = await self.exchange.fetch_my_trades(symbol, limit=100)
                for trade in symbol_trades:
                    # Deduplication and Persistance
                    is_new = self.db.save_trade(trade)
                    if is_new:
                        logger.info(f"[Bot] New Trade Recorded: {trade['id']} {trade['side']} {trade['symbol']} PnL: {trade['pnl']}")
                        self.current_history.append(trade)
                        
                        # Alerta de Trade Sospechoso (Phase 4)
                        if trade.get('is_suspicious'):
                            alert_msg = (f"🚨 **ALERTA: Trade Sospechoso Detectado**\n"
                                         f"ID: {trade['id']}\n"
                                         f"Symbol: {trade['symbol']}\n"
                                         f"PnL: 0.0 (Cierre significativo detectado)\n"
                                         f"**Acción Sugerida**: Revisar manualmente en Binance.")
                            await self.telegram.send_error_alert(alert_msg)
                
                # In-memory history for dashboard (limited)
                if len(self.current_history) > 500:
                    self.current_history = self.current_history[-500:]
            
            # Notify for Grid Initialization (Batched)
            grid_init_signals = [s for s in signals if s.strategy == "GridInitial"]
            if grid_init_signals:
                now = time.time()
                last_time = self.last_grid_update.get(symbol, 0)
                if now - last_time > 300: # 5 minute cooldown
                    # Format levels for display
                    levels_msg = "\n".join([
                        f"• {s.side.name} @ {s.price:.2f} ({s.amount:.3f})" 
                        for s in sorted(grid_init_signals, key=lambda x: x.price)
                    ])
                    
                    await self.telegram.send_message(
                        f"♻️ **Grid Iniciado** para {symbol}\n"
                        f"**Hora:** {datetime.now().strftime('%H:%M:%S')}\n"
                        f"**Niveles ({len(grid_init_signals)}):**\n{levels_msg}"
                    )
                    self.last_grid_update[symbol] = now

            # 5. Execution Logic
            for signal in signals:
                if not signal.price: continue
                
                # Enrich signal with amount if missing
                if not signal.amount:
                    signal.amount = self.risk_manager.calculate_position_size(
                        symbol, signal.price, signal.stop_loss, self.exchange
                    )
                
                # Safe Mode Check: Skip new entries if active
                if self.risk_manager.is_safe_mode and signal.action in [SignalAction.ENTER_LONG, SignalAction.ENTER_SHORT, SignalAction.GRID_PLACE]:
                    logger.warning(f"[Bot] SAFE MODE ACTIVE: Blocking entry signal for {symbol}")
                    continue

                if self.config.ANALYSIS_ONLY:
                    self.paper_manager.execute_signal(signal)
                    # Notify on Paper Trade? Maybe optionally.
                else:
                    # LIVE EXECUTION
                    if signal.action == SignalAction.GRID_PLACE:
                        # Place Limit Order
                        yield_order = await self.execution.place_order(
                            symbol, signal.side.value.lower(), 'limit', signal.amount, signal.price
                        )
                        if yield_order and yield_order.get('id'):
                            # Feedback ID to strategy for reconciliation tracking
                            self.neutral_grid.update_order_id(symbol, signal.price, yield_order['id'])
                            logger.info(f"[LIVE] Grid Limit Order: {signal.side} @ {signal.price} ID: {yield_order['id']}")
                            
                            # Notify ONLY for Grid Replenishments (implies a fill occurred)
                            if signal.strategy == "GridReplenish":
                                filled_side = "BUY" if signal.side == Side.SHORT else "SELL"
                                await self.telegram.send_trade_alert(
                                    symbol, filled_side, signal.price, signal.amount, "Grid Fill & Replenish"
                                )
                                self.trades_today += 1
                            elif signal.strategy == "GridInitial":
                                logger.info(f"Grid Initialized for {symbol} (No Alert)")

                    elif signal.action in [SignalAction.ENTER_LONG, SignalAction.ENTER_SHORT]:
                        # 1. Market Entry
                        order = await self.execution.place_order(
                            symbol, signal.side.value.lower(), 'market', signal.amount
                        )
                        if order:
                            logger.info(f"[LIVE] Market Entry Executed: {order.get('id')}")
                            await self.telegram.send_trade_alert(
                                symbol, signal.side.value, signal.price, signal.amount, f"Market Entry ({signal.strategy})"
                            )
                            self.trades_today += 1
                            
                            # 2. Place SL (Stop Market)
                            if signal.stop_loss:
                                sl_side = 'sell' if signal.side == Side.LONG else 'buy'
                                sl_order = await self.execution.place_order(
                                    symbol, sl_side, 'stop', signal.amount, signal.stop_loss,
                                    params={'stopPrice': signal.stop_loss, 'reduceOnly': True}
                                )
                                logger.info(f"[LIVE] Stop Loss Placed @ {signal.stop_loss}")
                            
                            # 3. Place TP (Limit)
                            if signal.take_profit:
                                tp_side = 'sell' if signal.side == Side.LONG else 'buy'
                                tp_order = await self.execution.place_order(
                                    symbol, tp_side, 'limit', signal.amount, signal.take_profit,
                                    params={'reduceOnly': True}
                                )
                                logger.info(f"[LIVE] Take Profit Placed @ {signal.take_profit}")

                            # 4. Place DCA Orders (if any) and track them
                            dca_levels_meta = signal.meta.get('dca_levels', [])
                            for dca_m in dca_levels_meta:
                                dca_order = await self.execution.place_order(
                                    symbol, signal.side.value.lower(), 'limit', dca_m['amount'], dca_m['price']
                                )
                                if dca_order and dca_order.get('id'):
                                    self.trend_dca.update_order_id(symbol, dca_m['price'], dca_order['id'])
                                    logger.info(f"[LIVE] DCA Order placed @ {dca_m['price']} ID: {dca_order['id']}")

                    elif signal.action in [SignalAction.EXIT_LONG, SignalAction.EXIT_SHORT]:
                        # Close Position
                        await self.execution.place_order(
                            symbol, signal.side.value.lower() == 'long' and 'sell' or 'buy', 'market', signal.amount,
                            params={'reduceOnly': True}
                        )
                        logger.info(f"[LIVE] Position Closed: {symbol}")
                        await self.telegram.send_trade_alert(
                            symbol, "CLOSE", price, signal.amount, f"Exit ({signal.strategy})"
                        )
            
            # Paper Trading Logging
            self._append_paper_record(
                symbol=symbol,
                price=price,
                regime=regime,
                signals_count=len(signals),
                virtual_equity=self.paper_manager.get_equity(current_prices)
            )

        # Periodic Summary (every 6 hours)
        now = time.time()
        if now - self.last_summary_time > 21600:  # 6 hours = 21600s
            uptime = str(datetime.now() - self.start_time).split('.')[0]
            await self.telegram.send_message(
                f"📊 **Resumen Periódico**\n"
                f"⏱ Uptime: {uptime}\n"
                f"💰 Equity: {equity:.2f} USDT\n"
                f"📈 PnL: {unrealized_pnl:+.2f} USDT\n"
                f"🔄 Iteraciones: {self.iteration_count}\n"
                f"📋 Trades hoy: {self.trades_today}"
            )
            self.last_summary_time = now

        # Write unified dashboard state
        self._write_dashboard_state(equity, unrealized_pnl, current_prices)

    def update_status(self, status):
        uptime = str(datetime.now() - self.start_time).split(".")[0]
        status_data = {
            "status": status, "uptime": uptime,
            "mode": "Paper" if self.config.USE_TESTNET else "Live",
            "last_loop": datetime.now().isoformat()
        }
        with open("status.json", "w") as f: json.dump(status_data, f, indent=4)

    def _write_dashboard_state(self, equity, unrealized_pnl, current_prices):
        """Write unified state for the dashboard — works in both paper and live modes."""
        try:
            if self.config.ANALYSIS_ONLY:
                balance = self.paper_manager.state.get("balance", 0)
                positions = self.paper_manager.state.get("positions", {})
                pending = self.paper_manager.state.get("pending_orders", [])
                history = self.paper_manager.state.get("history", [])
            else:
                balance = equity - unrealized_pnl
                positions = self.current_positions
                pending = self.current_orders
                history = self.current_history

            # Sort history by date descending
            if history:
                history = sorted(history, key=lambda x: str(x.get('closed_at', '')), reverse=True)

            state = {
                "balance": round(balance, 2),
                "equity": round(equity, 2),
                "unrealized_pnl": round(unrealized_pnl, 2),
                "mode": "Paper" if self.config.ANALYSIS_ONLY else ("Testnet" if self.config.USE_TESTNET else "Live"),
                "positions": positions,
                "pending_orders": pending,
                "history": history[:100],  # 100 newest trades
                "regimes": self.current_regimes,
                "prices": {s: round(p, 2) for s, p in current_prices.items()},
                "iteration": self.iteration_count,
                "timestamp": datetime.now().isoformat(),
                "uptime": str(datetime.now() - self.start_time).split(".")[0],
            }
            with open("dashboard_state.json", "w") as f:
                json.dump(state, f, indent=2, default=str)
        except Exception as e:
            logger.warning(f"Failed to write dashboard state: {e}")

    def _append_paper_record(self, **kwargs):
        record = {'ts': datetime.utcnow().isoformat(), **kwargs}
        with open('papers.jsonl', 'a') as f: f.write(json.dumps(record) + "\n")

if __name__ == "__main__":
    runner = BotRunner()
    asyncio.run(runner.run())
