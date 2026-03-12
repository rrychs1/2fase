import asyncio
import time
import json
import os
from dotenv import load_dotenv
load_dotenv()
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
from logging_monitoring.telegram_alert_service import TelegramAlertService
from state.state_manager import write_bot_state

logger = setup_logger()

class BotRunner:
    def __init__(self, config=None, exchange=None, risk_manager=None, data_engine=None):
        from data.db_manager import DbManager
        from risk.circuit_breaker import CircuitBreaker
        
        self.start_time = datetime.now()
        self.config = config or Config()
        self.exchange = exchange or ExchangeClient()
        self.data_engine = data_engine or DataEngine(self.exchange)
        self.regime_detector = RegimeDetector()
        self.db = DbManager() # Senior Audit Phase 4
        self.circuit_breaker = CircuitBreaker() # Senior Audit Phase 5
        
        self.neutral_grid = NeutralGridStrategy(self.config)
        self.trend_dca = TrendDcaStrategy(self.config)
        self.router = StrategyRouter(self.neutral_grid, self.trend_dca)
        
        self.risk_manager = RiskManager(self.config)
        self.execution = ExecutionEngine(self.exchange, self.config)
        self.paper_manager = PaperManager()
        self.telegram = TelegramAlertService()
        self.last_grid_update = {}
        self.iteration_count = 0
        self.trades_today = 0
        self.last_summary_time = 0
        
        # Phase 22: Operational Mode Object
        self.status = {
            "trading_enabled": not self.config.ANALYSIS_ONLY,
            "paper_trading_enabled": self.config.ANALYSIS_ONLY,
            "telegram_available": self.telegram.is_healthy(),
            "exchange_connected": False,
            "last_change_reason": "Bot initialized"
        }
        
        # Operational Metrics (Observability Phase 10)
        self.metrics = {
            "signals_processed": 0,
            "orders_placed": 0,
            "orders_failed": 0,
            "errors": 0
        }
        # Dashboard state tracking
        self.last_error = None
        self.last_alert_flush = time.time()
        self.current_regimes = {}
        self.current_prices = {}
        self.current_positions = {}
        self.current_orders = []
        self.current_history = self.db.get_recent_trades(limit=100) # Load last 100 from DB on start
        
        # Rename realized_pnl to pnl for dashboard compatibility
        for t in self.current_history:
            if 'realized_pnl' in t and 'pnl' not in t:
                t['pnl'] = t['realized_pnl']
        self.update_status("Initialized")

    async def run(self):
        mode_str = "SIM" if self.config.TRADING_ENV == 'SIM' else ("Analysis Only (Paper)" if self.config.ANALYSIS_ONLY else ("Testnet" if self.config.USE_TESTNET else "LIVE"))
        logger.info(f"Starting Async Bot Runner [Mode: {mode_str}]...")
        
        bot_username = await self.telegram.verify_bot()
        startup_msg = f"🤖 **Bot Iniciado** (@{bot_username})\nModo: " + ("Testnet" if self.config.USE_TESTNET else "LIVE")
        logger.info(f"Risk Hierarchy: Kill Switch -> Safe Mode -> Daily Loss -> Cooldown")
        await self.telegram.info(startup_msg, force=True)
        
        # Phase 20/21: Exchange Health Check at Startup
        try:
            balance = await self.exchange.fetch_balance()
            equity = balance.get('total', {}).get('USDT', 0.0)
            logger.info(f"✅ Exchange connection verified. Equity: {equity} USDT")
            self.status["exchange_connected"] = True
            
            # Phase 21: Startup Ping
            await self.telegram.info(f"✅ **Bot iniciado correctamente**\nEstado: `Conectado`\nEquity: `{equity:.2f} USDT`", force=True)
        except Exception as conn_err:
            logger.critical(f"❌ Exchange connection FAILED: {conn_err}")
            self.status["exchange_connected"] = False
            self.status["last_change_reason"] = f"Conn failed: {conn_err}"
            await self.telegram.critical(f"🚨 **CONEXIÓN FALLIDA**: Modo solo lectura activado.\nError: `{conn_err}`", force=True)
            self.risk_manager.is_high_caution = True # Block entries

        await self.exchange.init()
        
        if not self.config.ANALYSIS_ONLY:
            for symbol in self.config.SYMBOLS:
                await self.exchange.set_leverage(symbol, self.config.LEVERAGE)

        try:
            while True:
                start_iter = time.time()
                try:
                    await self.exchange._apply_backoff() # Phase 5
                    await self.iterate()
                except Exception as e:
                    etype = type(e).__name__
                    short_msg = str(e)[:100]
                    self.last_error = {"type": etype, "msg": short_msg, "ts": datetime.now().isoformat()}
                    
                    # Lead Developer: Specialized TypeError Diagnostic (Task 69)
                    if isinstance(e, TypeError):
                        logger.critical(f"TYPE ERROR DETECTED in bot loop: {e}")
                        # Log types of suspicious variables
                        logger.debug(f"State Types: iteration={type(self.iteration_count)}, exchange={type(self.exchange)}, telegram={type(self.telegram)}")
                    
                    logger.error(f"Error in iteration loop: {e}", exc_info=True)
                    self.circuit_breaker.report_error()
                    
                    # Senior Hardening: Rich Error Context
                    ctx = f"Modo: `{mode_str}`\nIteración: `{self.iteration_count}`\n"
                    await self.telegram.critical(
                        f"❌ **Error Crítico de Bucle**\n{ctx}Tipo: `{etype}`\nMensaje: `{short_msg}`\n_Detalle técnico en servidor._",
                        dedup_key=f"loop_error_{etype}"
                    )
                
                # Periodic Alert Flush (e.g. every 5 mins for better responsiveness)
                if time.time() - self.last_alert_flush > 300:
                    await self.telegram.flush_alerts()
                    self.last_alert_flush = time.time()
                
                elapsed = time.time() - start_iter
                logger.info(f"Cycle processed | symbols={len(self.config.SYMBOLS)} duration={elapsed*1000:.0f}ms")
                
                sleep_time = max(1, self.config.POLLING_INTERVAL - elapsed)
                await asyncio.sleep(sleep_time)
        finally:
            await self.telegram.info("🛑 **Bot Detenido**", force=True)
            await self.exchange.close()

    async def iterate(self):
        self.iteration_count += 1
        
        # Phase 5: Check Circuit Breaker & Alerts Health
        cb_tripped = self.circuit_breaker.is_tripped()
        if cb_tripped: # Phase 24: Decouple Telegram health from trading block
            if not self.risk_manager.is_high_caution:
                reason = "Circuit Breaker Tripped"
                logger.critical(f"ACTIVATING HIGH CAUTION MODE: {reason}")
                self.risk_manager.is_high_caution = True
        else:
            if self.risk_manager.is_high_caution:
                logger.info("Deactivating High Caution Mode. Systems normalized.")
                self.risk_manager.is_high_caution = False

        self.update_status("Running" if not self.risk_manager.is_high_caution else "HIGH CAUTION")
        
        current_prices = {}
        self.current_regimes = {}
        self.current_positions = {}
        self.current_orders = []
        # 0. Fetch latest prices for all symbols first to accurately estimate equity/risk
        for symbol in self.config.SYMBOLS:
            df_4h = await self.data_engine.fetch_ohlcv(symbol, self.config.TF_GRID, limit=self.config.CANDLES_ANALYSIS_LIMIT)
            if df_4h is not None and len(df_4h) > 0:
                current_prices[symbol] = df_4h.iloc[-1]['close']

        # 1. Sync Account State with accurate prices
        try:
            if self.config.ANALYSIS_ONLY:
                equity = self.paper_manager.get_equity(current_prices)
                balance_val = self.paper_manager.state.get("balance", 0.0)
                if not isinstance(equity, (int, float)) or not isinstance(balance_val, (int, float)):
                    logger.error(f"[Sync] Invalid Paper types: equity={type(equity)}, balance={type(balance_val)}")
                    unrealized_pnl = 0.0
                else:
                    unrealized_pnl = equity - balance_val
            else:
                balance = await self.exchange.fetch_balance()
                equity = float(balance.get('total', {}).get('USDT', 0.0))
                unrealized_pnl = await self.execution.get_account_pnl()
            
            # Robustness: Coerce to float
            equity = float(equity) if isinstance(equity, (int, float)) else 0.0
            unrealized_pnl = float(unrealized_pnl) if isinstance(unrealized_pnl, (int, float)) else 0.0
            
            # Sync reference equity for the entire cycle
            drift_alert, drift_val = self.risk_manager.sync_reference_equity(equity, unrealized_pnl)
            if drift_alert:
                alert_msg = (f"⚠️ **ALERTA DE SEGURIDAD: Deriva de Equity**\n"
                             f"Se ha detectado un cambio inexplicable de {drift_val*100:.2f}%\n"
                             f"**Modo Seguro ACTIVADO**. Se bloquean nuevas entradas.")
                await self.telegram.error(alert_msg, dedup_key="equity_drift_alert")
            
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
                await self.telegram.critical(msg, dedup_key="kill_switch_active")
                
                if self.config.ANALYSIS_ONLY:
                    self.paper_manager.state["positions"] = {}
                    self.paper_manager.state["pending_orders"] = []
                else:
                    await self.execution.close_all_positions()
                
                # Write state before returning to show KILL SWITCH status
                self._write_dashboard_state(equity, unrealized_pnl, current_prices)
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
            
            # Phase 20: Explicit Block Diagnostics
            blockers = []
            if self.risk_manager.is_safe_mode: blockers.append("SAFE MODE")
            if self.risk_manager.is_high_caution: blockers.append("HIGH CAUTION")
            if self.risk_manager.is_kill_switch_active: blockers.append("KILL SWITCH")
            if self.config.ANALYSIS_ONLY: blockers.append("PAPER ONLY")
            
            block_msg = f" | BLOCKERS: {', '.join(blockers)}" if blockers else " | ENABLED"
            
            # Phase 21/22: High-Level Traceability Log (Always visible)
            logger.info(f"[{symbol}] Price: {price:.2f} | Regime: {regime.upper()} | Pos: {pos_info}{block_msg}")
            
            market_state = {
                'price': price,
                'df': df_trend,
                'volume_profile': vp,
                'equity': equity,
                'position': position
            }
            # 4. Generate Strategy Signals
            signals = await self.router.route_signals(symbol, regime, market_state)
            self.metrics["signals_processed"] += len(signals)
            
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
            if signals:
                logger.info(f"[{symbol}] Generated {len(signals)} signals: {[s.action.value for s in signals]}")
                # Phase 21: Signal Alert
                await self.telegram.info(f"🔍 **Señal Detectada**: {symbol}\nAcciones: `{[s.action.value for s in signals]}`\nRegimen: `{regime.upper()}`")
            else:
                logger.debug(f"[{symbol}] No signals generated in {regime} mode.")

            if grid_init_signals:
                now = time.time()
                last_time = self.last_grid_update.get(symbol, 0)
                if now - last_time > 300: # 5 minute cooldown
                    # Format levels for display
                    levels_msg = "\n".join([
                        f"• {s.side.name} @ {s.price:.2f} ({s.amount:.3f})" 
                        for s in sorted(grid_init_signals, key=lambda x: x.price)
                    ])
                    
                    await self.telegram.info(
                        f"♻️ **Grid Iniciado** para {symbol}\n"
                        f"**Hora:** {datetime.now().strftime('%H:%M:%S')}\n"
                        f"**Niveles ({len(grid_init_signals)}):**\n{levels_msg}"
                    )
                    self.last_grid_update[symbol] = now

            # 5. Execution Logic (Senior Hardening: Decoupled per Signal)
            for signal in signals:
                if not signal.price: continue
                
                # Enrich signal with amount if missing
                if not signal.amount:
                    # Risk manager will try to calculate based on equity & risk model
                    signal.amount = self.risk_manager.calculate_position_size(symbol, signal.price, getattr(signal, 'stop_loss', None), self.exchange)
                    if signal.amount <= 0:
                        # Phase 21: Diagnostic Alert for Blocked Signal
                        reason = "Size Calculation Failed (Risk Manager Blocked)"
                        logger.warning(f"[Bot] Signal for {symbol} BLOCKED: {reason}")
                        await self.telegram.warning(f"⚠️ **Señal Bloqueada**: {symbol}\nMotivo: `{reason}`", dedup_key=f"block_{symbol}")
                        continue

                try:
                    # Phase 21: Pre-Execution Log/Alert
                    if self.risk_manager.is_safe_mode and signal.action in [SignalAction.ENTER_LONG, SignalAction.ENTER_SHORT, SignalAction.GRID_PLACE]:
                        reason = f"SAFE MODE ACTIVE (Equity drift or invalid data)"
                        logger.warning(f"[Bot] {symbol} signal BLOCKED: {reason}")
                        await self.telegram.warning(f"⚠️ **Entrada Bloqueada**: {symbol}\nMotivo: `{reason}`", dedup_key=f"safe_block_{symbol}")
                        continue
                    elif self.risk_manager.is_high_caution:
                        reason = "HIGH CAUTION (Circuit Breaker Halted)"
                        logger.warning(f"[Bot] {symbol} signal BLOCKED: {reason}")
                        await self.telegram.warning(f"⚠️ **Operación Bloqueada**: {symbol}\nMotivo: `{reason}`", dedup_key=f"caution_block_{symbol}")
                        continue
                    elif self.risk_manager.is_kill_switch_active:
                        reason = "KILL SWITCH ACTIVE (Daily loss limit reached)"
                        logger.warning(f"[Bot] {symbol} signal BLOCKED: {reason}")
                        await self.telegram.critical(f"🛑 **TRADE BLOQUEADO**: {symbol}\nMotivo: `{reason}`", dedup_key=f"kill_block_{symbol}")
                        continue
                    
                    logger.info(f"[Bot] {symbol} => EXECUTION START: {signal.action.value} @ {signal.price} (Size: {signal.amount})")
                    await self.telegram.info(f"🚀 **Ejecutando**: {signal.action.value} {symbol}\nPrecio: `{signal.price}`\nCantidad: `{signal.amount}`")
                    
                    # PAPER EXECUTION
                    # Phase 21: Consolidated Execution Logic
                    order_res = None
                    if self.config.ANALYSIS_ONLY:
                        self.paper_manager.execute_signal(signal)
                        order_res = {"id": "PAPER_ORDER", "status": "closed"}
                        logger.info(f"[Bot] PAPER: Executed {signal.action.value} {symbol}")
                    else:
                        # 1. Strategy Specific Execution
                        if signal.action == SignalAction.GRID_PLACE:
                            order_res = await self.execution.place_order(symbol, signal.side.name.lower(), 'limit', signal.amount, signal.price)
                            if order_res and order_res.get('id'):
                                self.neutral_grid.update_order_id(symbol, signal.price, order_res['id'])
                        
                        elif signal.action in [SignalAction.ENTER_LONG, SignalAction.ENTER_SHORT]:
                            order_res = await self.execution.place_order(symbol, signal.side.name.lower(), 'market', signal.amount)
                            # Side orders (SL/TP/DCA)
                            if order_res and order_res.get('id'):
                                if signal.stop_loss:
                                    sl_side = 'sell' if signal.side == Side.LONG else 'buy'
                                    await self.execution.place_order(symbol, sl_side, 'stop', signal.amount, signal.stop_loss, params={'stopPrice': signal.stop_loss, 'reduceOnly': True})
                                if signal.take_profit:
                                    tp_side = 'sell' if signal.side == Side.LONG else 'buy'
                                    await self.execution.place_order(symbol, tp_side, 'limit', signal.amount, signal.take_profit, params={'reduceOnly': True})
                                
                                dca_levels_meta = signal.meta.get('dca_levels', [])
                                for dca_m in dca_levels_meta:
                                    dca_order = await self.execution.place_order(symbol, signal.side.name.lower(), 'limit', dca_m['amount'], dca_m['price'])
                                    if dca_order and dca_order.get('id'):
                                        self.trend_dca.update_order_id(symbol, dca_m['price'], dca_order['id'])

                        elif signal.action in [SignalAction.EXIT_LONG, SignalAction.EXIT_SHORT]:
                            order_res = await self.execution.place_order(symbol, 'sell' if signal.side == Side.LONG else 'buy', 'market', signal.amount, params={'reduceOnly': True})

                    # 2. Alert & Metrics Result
                    if order_res:
                        logger.info(f"✅ [Bot] {symbol} => {signal.action.value} SUCCESS")
                        self.metrics["orders_placed"] += 1
                        if signal.action in [SignalAction.GRID_PLACE, SignalAction.ENTER_LONG, SignalAction.ENTER_SHORT]:
                            await self.telegram.trade(symbol, signal.side.name, signal.price, signal.amount, signal.strategy)
                        elif signal.action in [SignalAction.EXIT_LONG, SignalAction.EXIT_SHORT]:
                            await self.telegram.trade(symbol, "CLOSE", signal.price, signal.amount, f"Exit ({signal.strategy})")
                    else:
                        logger.error(f"❌ [Bot] {symbol} => {signal.action.value} FAILED")
                        self.metrics["orders_failed"] += 1
                        await self.telegram.error(f"❌ **Orden Fallida**: {symbol}\nAcción: `{signal.action.value}`")
                except Exception as signal_err:
                    s_type = type(signal_err).__name__
                    logger.error(f"[{symbol}] Failed to execute signal {signal.action}: {signal_err}", exc_info=True)
                    await self.telegram.warning(
                        f"⚠️ **Fallo de Ejecución ({symbol})**\nAcción: `{signal.action.value}`\nError: `{s_type}`"
                    )
            
            # Senior Audit Phase 17: Paper Trading Logging (Safe execution)
            if self.config.PAPER_TRADING_ENABLED:
                try:
                    self._append_paper_record(
                        symbol=symbol,
                        price=price,
                        regime=regime,
                        signals_count=len(signals),
                        virtual_equity=self.paper_manager.get_equity(current_prices)
                    )
                except Exception as e:
                    logger.debug(f"Paper record skipped: {e}")

        # Periodic Summary (every 6 hours)
        now = time.time()
        if now - self.last_summary_time > 21600:  # 6 hours = 21600s
            uptime = str(datetime.now() - self.start_time).split('.')[0]
            await self.telegram.info(
                f"📊 **Resumen Periódico**\n"
                f"⏱ Uptime: {uptime}\n"
                f"💰 Equity: {equity:.2f} USDT\n"
                f"📈 PnL: {unrealized_pnl:+.2f} USDT\n"
                f"🔄 Iteraciones: {self.iteration_count}\n"
                f"📋 Trades hoy: {self.trades_today}",
                dedup_key="periodic_summary"
            )
            self.last_summary_time = now

        # Write unified dashboard state (Safe execution)
        try:
            self._write_dashboard_state(equity, unrealized_pnl, current_prices)
        except Exception as e:
            logger.warning(f"Failed to write dashboard state in cycle: {e}")

    def _append_paper_record(self, symbol, price, regime, signals_count, virtual_equity):
        """Senior Audit: Proxy to PaperManager to encapsulate persistence logic."""
        if not hasattr(self, 'paper_manager') or not self.paper_manager:
            return
            
        try:
            self.paper_manager.append_equity_record(
                symbol=symbol,
                price=price,
                regime=regime,
                signals_count=signals_count,
                equity=virtual_equity
            )
        except Exception as e:
            logger.debug(f"[SENIOR] Paper proxy failure: {e}")

    def update_status(self, status):
        """Update both memory status (Phase 22) and legacy status.json."""
        uptime = str(datetime.now() - self.start_time).split(".")[0]

        # Update Phase 22 Object
        self.status["last_change_reason"] = status
        self.status["telegram_available"] = self.telegram.is_healthy()

        status_data = {
            "running": True,
            "status": status,
            "uptime": uptime,
            "mode": "Paper" if self.config.ANALYSIS_ONLY else ("Testnet" if self.config.USE_TESTNET else "Live"),
            "last_loop": datetime.now().isoformat(),
            "full_status": self.status,
        }
        write_bot_state("status.json", status_data)

    def _write_dashboard_state(self, equity, unrealized_pnl, current_prices):
        """Write unified state for the dashboard — uses state_manager for atomic writes."""
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
                history = list(self.current_history)

            # Sort history by date descending
            if history:
                history = sorted(history, key=lambda x: str(x.get('closed_at', '')), reverse=True)

            state = {
                "running": True,
                "balance": round(balance, 2),
                "equity": round(equity, 2),
                "unrealized_pnl": round(unrealized_pnl, 2),
                "mode": "Paper" if self.config.ANALYSIS_ONLY else ("Testnet" if self.config.USE_TESTNET else "Live"),
                "positions": positions,
                "pending_orders": pending,
                "history": history[:100],
                "global_stats": self.db.get_stats(),
                "regimes": self.current_regimes,
                "prices": {s: round(p, 2) for s, p in current_prices.items()},
                "iteration": self.iteration_count,
                "uptime": str(datetime.now() - self.start_time).split(".")[0],
                "metrics": self.metrics,
                "status": self.status,
                "exchange_status": "Connected" if self.status["exchange_connected"] else "Failed",
                "last_error": self.last_error,
                "telegram_healthy": self.telegram.is_healthy(),
            }
            state_path = os.getenv("STATE_FILE", "data/dashboard_state.json")
            write_bot_state(state_path, state)
        except Exception as e:
            logger.warning(f"Failed to write dashboard state: {e}")

if __name__ == "__main__":
    runner = BotRunner()
    asyncio.run(runner.run())
