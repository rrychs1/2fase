import asyncio
import pandas as pd
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
from execution.execution_router import ExecutionRouter
from regime.volatility_detector import VolatilityRegimeDetector
from common.types import Side, SignalAction
from logging_monitoring.logger import setup_logger
from logging_monitoring.telegram_alert_service import TelegramAlertService
from state.state_manager import write_bot_state
import traceback # Added for detailed error logging
from logging_monitoring.metrics_server import (
    start_metrics_exporter, 
    bot_unrealized_pnl, 
    bot_daily_drawdown_pct, 
    bot_current_exposure, 
    bot_system_health, 
    bot_ws_connected
)

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
        self.strategy_router = StrategyRouter(self.neutral_grid, self.trend_dca)
        self.volatility_detector = VolatilityRegimeDetector()
        
        from data.websocket_manager import WebsocketManager
        self.ws_manager = WebsocketManager(self.config)
        
        self.risk_manager = RiskManager(self.config)
        self.execution_router = ExecutionRouter(self.exchange, self.config)
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
            # 0. Startup State Synchronization
            if self.config.EXECUTION_MODE == 'LIVE':
                logger.info("[Startup Sync] Reconciling memory with Exchange open orders...")
                for s_symbol in self.config.SYMBOLS:
                    try:
                        open_orders = await self.exchange.fetch_open_orders(s_symbol)
                        self.neutral_grid.reconcile_with_exchange(s_symbol, open_orders)
                        self.trend_dca.reconcile_with_exchange(s_symbol, open_orders)
                    except Exception as e:
                        logger.warning(f"[Startup Sync] Failed to sync orders for {s_symbol}: {e}")

            # 1. Seed Initial Data via REST (Polling) for all symbols
            logger.info("Seeding initial data before WS/Polling loop...")
            for symbol in self.config.SYMBOLS:
                await self.data_engine.fetch_ohlcv(symbol, self.config.TF_GRID, limit=self.config.CANDLES_ANALYSIS_LIMIT)
                await self.data_engine.fetch_ohlcv(symbol, self.config.TF_TREND, limit=self.config.CANDLES_ANALYSIS_LIMIT)

            if getattr(self.config, 'USE_WEBSOCKETS', True):
                # WEBSOCKET MODE
                logger.info("Initializing Websocket Event Loop...")
                for symbol in self.config.SYMBOLS:
                    self.ws_manager.add_subscription(symbol, [self.config.TF_GRID, self.config.TF_TREND])
                
                asyncio.create_task(self.ws_manager.connect())
                asyncio.create_task(self._heartbeat_loop())
                
                # Consume events from queue
                while True:
                    event = await self.ws_manager.event_queue.get()
                    start_iter = time.time()
                    try:
                        # 1. Update internal DataFrame fast addition
                        await self.data_engine.update_ohlcv(event)
                        logger.debug(f"[WS] Processed closed candle: {event.symbol} {event.timeframe}")
                        
                        # 2. Trigger Strategy Evaluation specifically for this symbol
                        await self.exchange._apply_backoff() 
                        await self.iterate(target_symbol=event.symbol)
                        
                    except Exception as e:
                        self._handle_loop_error(e, f"WS_SIM ({event.symbol})")
                    finally:
                        self.ws_manager.event_queue.task_done()
                        self._flush_alerts_and_log(start_iter)
            else:
                # LEGACY POLLING MODE
                while True:
                    start_iter = time.time()
                    try:
                        await self.exchange._apply_backoff()
                        await self.iterate()
                    except Exception as e:
                        self._handle_loop_error(e, mode_str)
                    
                    self._flush_alerts_and_log(start_iter)
                    elapsed = time.time() - start_iter
                    sleep_time = max(1, self.config.POLLING_INTERVAL - elapsed)
                    await asyncio.sleep(sleep_time)

        finally:
            # Clean boot flag on graceful exit
            if os.path.exists(self.boot_flag_file):
                try: os.remove(self.boot_flag_file)
                except: pass
                
            await self.ws_manager.stop()
            await self.telegram.info("🛑 **Bot Detenido**", force=True)
            await self.exchange.close()

    async def _heartbeat_loop(self):
        """Asynchronous task reporting detailed subsystem health every minute."""
        interval = getattr(self.config, 'HEARTBEAT_INTERVAL', 60)
        while True:
            await asyncio.sleep(interval)
            
            # Formulate subsystem status
            ws_state = "Connected" if getattr(self.ws_manager, 'ws', None) and not self.ws_manager.ws.closed else "Disconnected"
            last_api = getattr(self.exchange, 'last_api_success', 0)
            api_lag = time.time() - last_api if last_api > 0 else -1
            
            # Prometheus Updates
            bot_ws_connected.set(1 if ws_state == "Connected" else 0)
            bot_system_health.set(0 if self.risk_manager.is_kill_switch_active or self.risk_manager.is_safe_mode else 1)
            
            log_msg = (
                f"[HEARTBEAT] Equity: {self.risk_manager.reference_equity:.2f} | "
                f"WS: {ws_state} | "
                f"API Last Success: {api_lag:.1f}s ago | "
                f"Iter: {self.iteration_count}"
            )
            logger.info(log_msg)

    def _handle_loop_error(self, e, mode_str):
        etype = type(e).__name__
        short_msg = str(e)[:100]
        self.last_error = {"type": etype, "msg": short_msg, "ts": datetime.now().isoformat()}
        if isinstance(e, TypeError):
            logger.critical(f"TYPE ERROR DETECTED in bot loop: {e}")
            logger.debug(f"State Types: iteration={type(self.iteration_count)}, exchange={type(self.exchange)}, telegram={type(self.telegram)}")
        logger.error(f"Error in iteration loop: {e}", exc_info=True)
        self.circuit_breaker.report_error()
        ctx = f"Modo: `{mode_str}`\nIteración: `{self.iteration_count}`\n"
        asyncio.create_task(self.telegram.critical(
            f"❌ **Error Crítico de Bucle**\n{ctx}Tipo: `{etype}`\nMensaje: `{short_msg}`\n_Detalle técnico en servidor._",
            dedup_key=f"loop_error_{etype}"
        ))

    def _flush_alerts_and_log(self, start_iter):
        if time.time() - self.last_alert_flush > 300:
            asyncio.create_task(self.telegram.flush_alerts())
            self.last_alert_flush = time.time()
        elapsed = time.time() - start_iter
        logger.info(f"Cycle processed | symbols={len(self.config.SYMBOLS)} duration={elapsed*1000:.0f}ms")

    async def iterate(self, target_symbol=None):
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
        
        # Subset of symbols if triggered by specific websocket event
        symbols_to_process = [target_symbol] if target_symbol else self.config.SYMBOLS

        # 0. Fetch latest prices to accurately estimate equity/risk
        for symbol in symbols_to_process:
            # First try the data engine cache (updated directly by WS or polling earlier)
            df_4h = self.data_engine.data.get((symbol, self.config.TF_GRID))
            if df_4h is None or len(df_4h) < 20:
                # Fallback to polling if cache missing
                df_4h = await self.data_engine.fetch_ohlcv(symbol, self.config.TF_GRID, limit=self.config.CANDLES_ANALYSIS_LIMIT)
            if df_4h is not None and len(df_4h) > 0:
                current_prices[symbol] = df_4h.iloc[-1]['close']

        # 1. Sync Account State with accurate prices
        try:
            equity, unrealized_pnl = await self.execution_router.get_equity_and_pnl(current_prices)
            
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
                msg = "💀 KILL SWITCH ACTIVATED: Cancelling orders and liquidating positions!"
                logger.critical(msg)
                bot_system_health.set(0) # Update metrics before returning
                await self.telegram.critical(msg, dedup_key="kill_switch_active")
                
                # Panic Liquidation: Cancel all limits/stops first
                for s_sym in self.config.SYMBOLS:
                    await self.exchange.cancel_all_orders(s_sym)
                
                # Panic Liquidation: Close open positions via ExecutionRouter
                await self.execution_router.close_all_positions(current_prices)
                
                # Write state before returning to show KILL SWITCH status
                self._write_dashboard_state(equity, unrealized_pnl, current_prices)
                return
            
            # Update Prometheus
            bot_unrealized_pnl.set(unrealized_pnl)
            
            # Drawdown pct
            if self.risk_manager.day_start_equity > 0:
                dd_pct = unrealized_pnl / self.risk_manager.day_start_equity
                bot_daily_drawdown_pct.set(dd_pct)
                
            # Current Exposure calculation
            total_exposure = 0.0
            positions_data = self.execution_router.get_state_metrics().get('positions', {})
            for sym, pos in positions_data.items():
                if isinstance(pos, dict):
                    qty = float(pos.get('amount', 0))
                    price = float(pos.get('average_price', current_prices.get(sym, 0)))
                    total_exposure += (qty * price)
            bot_current_exposure.set(total_exposure)

            self._write_dashboard_state(equity, unrealized_pnl, current_prices, target_symbol)
        except Exception as e:
            logger.warning(f"Failed to sync account state: {e}")
            equity = 10000.0 if self.config.ANALYSIS_ONLY else 0.0
            unrealized_pnl = 0.0

        for symbol in symbols_to_process:
            # 3. Update Data & Indicators
            # Try from internal memory cache first (populated by WS or initial seed)
            df_4h = self.data_engine.data.get((symbol, self.config.TF_GRID))
            df_trend = self.data_engine.data.get((symbol, self.config.TF_TREND))
            
            if df_4h is None or len(df_4h) < 20: 
                df_4h = await self.data_engine.fetch_ohlcv(symbol, self.config.TF_GRID, limit=self.config.CANDLES_ANALYSIS_LIMIT)
            if df_trend is None or len(df_trend) < 20:
                df_trend = await self.data_engine.fetch_ohlcv(symbol, self.config.TF_TREND, limit=self.config.CANDLES_ANALYSIS_LIMIT)
            
            if df_4h is None or df_trend is None or len(df_4h) < 20: continue
            
            price = current_prices.get(symbol, df_4h.iloc[-1]['close'])
            
            # Update Virtual Positions (Check SL/TP and Pending Orders)
            self.execution_router.update_positions({symbol: price})

            # 3. Indicator Calculation
            df_4h = add_standard_indicators(df_4h)
            df_trend = add_standard_indicators(df_trend)
            vp = compute_volume_profile(df_4h)
            
            # Volatility Analysis
            atr_series = self.volatility_detector.calculate_atr(df_4h)
            atr_val = atr_series.iloc[-1] if not pd.isna(atr_series.iloc[-1]) else (price * 0.02)
            volatility_regime = self.volatility_detector.detect_regime(df_4h)

            # 3. Transition Tolerance (Phase 3)
            # If regime changed, reconcile immediately to avoid orphan orders
            old_regime = self.current_regimes.get(symbol)
            regime = self.regime_detector.detect_regime(df_4h) # Original regime detection
            
            if old_regime and old_regime != regime:
                logger.warning(f"[{symbol}] REGIME CHANGE DETECTED: {old_regime} -> {regime}. Immediate reconciliation starting...")
                trans_orders = await self.exchange.fetch_open_orders(symbol)
                # Ensure strategies see the current orders before routing signals
                self.neutral_grid.reconcile_with_exchange(symbol, trans_orders)
                self.trend_dca.reconcile_with_exchange(symbol, trans_orders)
            
            self.current_regimes[symbol] = regime

            # 4. Strategy Analysis
            position = await self.execution_router.get_position(symbol)

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
                'position': position,
                'regime': regime,
                'volatility_regime': volatility_regime,
                'atr': atr_val,
                'unrealized_pnl': unrealized_pnl
            }
            # 4. Generate Strategy Signals
            signals = await self.strategy_router.route_signals(symbol, regime, market_state)
            self.metrics["signals_processed"] += len(signals)
            
            # Track Orders and History in Live Mode
            if self.config.EXECUTION_MODE == 'LIVE':
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

                # NEW: Inventory Risk Control
                allowed_amount = self.risk_manager.enforce_inventory_limits(symbol, signal, self.current_positions)
                if allowed_amount <= 0:
                    logger.warning(f"[Bot] Signal for {symbol} BLOCKED: Inventory limits exceeded.")
                    continue
                
                # Reduce size if necessary
                if allowed_amount < signal.amount:
                    logger.warning(f"[Bot] {symbol} Order size reduced from {signal.amount:.4f} to {allowed_amount:.4f} due to inventory limits.")
                    signal.amount = allowed_amount

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
                    
                    # EXECUTION via Router
                    order_res = await self.execution_router.execute_signal(
                        signal, neutral_grid=self.neutral_grid, trend_dca=self.trend_dca
                    )

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
        if self.config.EXECUTION_MODE != 'PAPER':
            return
            
        try:
            self.execution_router.paper_manager.append_equity_record(
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

    def _write_dashboard_state(self, equity, unrealized_pnl, current_prices, target_symbol=None):
        """Write unified state for the dashboard — uses state_manager for atomic writes."""
        try:
            if self.config.EXECUTION_MODE == 'LIVE':
                balance = equity - unrealized_pnl
                positions = self.current_positions
                pending = self.current_orders
                history = list(self.current_history)
            else:
                metrics = self.execution_router.get_state_metrics()
                balance = metrics["balance"]
                positions = metrics["positions"]
                pending = metrics["pending_orders"]
                history = metrics["history"]

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

    async def close(self):
        """Exhaustive resource cleanup for bot shutdown."""
        logger.info("[STOP] Shutting down bot subsystems...")
        
        # 1. Alerting systems
        if hasattr(self, 'telegram'):
            await self.telegram.close()
            
        # 2. Network/Exchange
        if hasattr(self, 'ws_manager') and self.ws_manager:
            await self.ws_manager.stop()
            
        if hasattr(self, 'exchange') and self.exchange:
            await self.exchange.close()
            
        # 3. Data/DB
        if hasattr(self, 'db'):
            # DbManager connections are closed per-call, but we ensure state
            pass
            
        logger.info("[STOP] Bot shutdown complete.")

if __name__ == "__main__":
    runner = BotRunner()
    asyncio.run(runner.run())
