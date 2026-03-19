import logging
from common.types import Side, SignalAction, Signal
from config.config_loader import Config
from execution.execution_engine import ExecutionEngine
from execution.paper_manager import PaperManager
from execution.shadow_executor import ShadowExecutor
from execution.order_validator import OrderValidator
from risk.core_risk_engine import CoreRiskEngine

logger = logging.getLogger(__name__)

class ExecutionRouter:
    """
    Routes execution and state read requests to the active executor.
    Supports SHADOW, PAPER, and LIVE modes.
    """
    def __init__(self, exchange_client, config: Config):
        self.config = config
        self.mode = self.config.EXECUTION_MODE
        
        self.live_engine = ExecutionEngine(exchange_client, config)
        self.paper_manager = PaperManager()
        self.shadow_executor = ShadowExecutor()
        self.exchange = exchange_client
        
        self.risk_engine = CoreRiskEngine(config, self.get_state_metrics)
        
        logger.info(f"[EXEC] ExecutionRouter initialized in {self.mode} mode.")

    async def calculate_liquidity_sizing(self, symbol: str, signal: Signal) -> tuple[float, float]:
        """
        Calculates the maximum allowed order size based on Order Book depth,
        spread, VWAP slippage, and safety haircuts.
        Returns (max_amount, mid_price).
        """
        amount = signal.amount
        mid_fallback = signal.price if signal.price else 0.0
        if amount <= 0: return 0.0, mid_fallback

        try:
            ob = await self.exchange.fetch_order_book(symbol, limit=100)
            if not ob or ob.get('bids') is None or ob.get('asks') is None:
                logger.warning(f"[Liquidity] Missing OB for {symbol}. Allowing size but flagging warning.")
                return amount, mid_fallback
                
            bids = ob['bids']
            asks = ob['asks']
            
            if not bids or not asks:
                logger.warning(f"[Liquidity] One side of OB for {symbol} is empty. Blocking.")
                return 0.0, mid_fallback

            best_bid = bids[0][0]
            best_ask = asks[0][0]
            mid_price = (best_bid + best_ask) / 2.0
            
            # 1. Spread Protection
            spread_pct = (best_ask - best_bid) / best_bid
            max_spread = getattr(self.config, 'MAX_SPREAD_PCT', 0.005)
            if spread_pct > max_spread:
                logger.warning(f"[Liquidity] Spread {spread_pct*100:.2f}% > Max {max_spread*100:.2f}%. Blocking.")
                return 0.0, mid_price

            # 2. Depth Calculation (1% from Mid)
            depth_vol = 0.0
            levels = asks if signal.side == Side.LONG or signal.action == SignalAction.EXIT_SHORT else bids
            limit_price = mid_price * 1.01 if levels is asks else mid_price * 0.99
            
            for price, qty in levels:
                if (levels is asks and price > limit_price) or (levels is bids and price < limit_price):
                    break
                depth_vol += qty

            # Apply Haircut and Ratio
            haircut = getattr(self.config, 'LIQUIDITY_HAIRCUT', 0.20)
            effective_depth = depth_vol * (1.0 - haircut)
            
            max_ratio = getattr(self.config, 'MAX_ORDER_DEPTH_RATIO', 0.10)
            max_allowed = effective_depth * max_ratio

            # 3. Target amount
            target_amount = min(amount, max_allowed)
            
            if target_amount <= 0:
                logger.warning(f"[Liquidity] {symbol} allowed depth <= 0. Blocked.")
                return 0.0, mid_price
                
            if target_amount < amount:
                logger.warning(f"[Liquidity] {symbol} Order > 10% Depth. Reduced {amount:.4f} -> {target_amount:.4f}")

            # 4. VWAP Slippage Check
            cumulative_vol = 0.0
            cumulative_notional = 0.0
            for price, qty in levels:
                take = min(qty, target_amount - cumulative_vol)
                cumulative_vol += take
                cumulative_notional += price * take
                if cumulative_vol >= target_amount:
                    break
                    
            if cumulative_vol > 0:
                vwap = cumulative_notional / cumulative_vol
                slippage = abs(vwap - mid_price) / mid_price
                max_slip = getattr(self.config, 'MAX_SLIPPAGE_PCT', 0.002)
                
                if slippage > max_slip:
                    logger.warning(f"[Liquidity] {symbol} VWAP Slippage {slippage*100:.2f}% > Max {max_slip*100:.2f}%.")
                    # Scale down the order exponentially based on excess slippage
                    slip_factor = max_slip / slippage
                    target_amount = target_amount * slip_factor
                    logger.warning(f"[Liquidity] Auto-scaled size to {target_amount:.4f} to fit slippage tolerance.")

            return target_amount, mid_price
            
        except Exception as e:
            logger.error(f"[Liquidity] Error calculating sizing for {symbol}: {e}")
            return amount, mid_fallback

    def get_state_metrics(self):
        """Returns the dictionary representation of state variables for the dashboard."""
        if self.mode == 'SHADOW':
            return {
                "balance": self.shadow_executor.state.get("balance", 0.0),
                "positions": self.shadow_executor.state.get("positions", {}),
                "pending_orders": [],
                "history": self.shadow_executor.state.get("history", [])
            }
        else: # PAPER works as fallback state for dashboard if not LIVE
            return {
                "balance": self.paper_manager.state.get("balance", 0.0),
                "positions": self.paper_manager.state.get("positions", {}),
                "pending_orders": self.paper_manager.state.get("pending_orders", []),
                "history": self.paper_manager.state.get("history", [])
            }

    async def get_equity_and_pnl(self, current_prices: dict):
        if self.mode == 'SHADOW':
            equity = self.shadow_executor.get_equity(current_prices)
            pnl = self.shadow_executor.get_account_pnl(current_prices)
            return equity, pnl
        elif self.mode == 'PAPER':
            equity = self.paper_manager.get_equity(current_prices)
            pnl = equity - self.paper_manager.state.get("balance", 0.0)
            return equity, pnl
        else:
            balance_data = await self.live_engine.exchange.fetch_balance()
            equity = float(balance_data.get('total', {}).get('USDT', 0.0))
            pnl = await self.live_engine.get_account_pnl()
            return equity, pnl

    async def get_position(self, symbol: str) -> dict:
        if self.mode == 'SHADOW':
            return self.shadow_executor.get_position(symbol)
        elif self.mode == 'PAPER':
            return self.paper_manager.state.get("positions", {}).get(symbol, {})
        else:
            return await self.live_engine.get_position(symbol)

    def update_positions(self, current_prices: dict):
        """Update virtual positions (Trigger SL/TP/Pending Limits)."""
        if self.mode == 'SHADOW':
            self.shadow_executor.update_positions(current_prices)
        elif self.mode == 'PAPER':
            self.paper_manager.update_positions(current_prices)

    async def close_all_positions(self, current_prices: dict = None):
        """Emergency Close All and Cancel Open Orders"""
        if self.mode == 'SHADOW':
            self.shadow_executor.close_all_positions(current_prices or {})
        elif self.mode == 'PAPER':
            self.paper_manager.state["positions"] = {}
            self.paper_manager.state["pending_orders"] = []
        else:
            await self.live_engine.close_all_positions()
            positions = await self.live_engine.fetch_positions()
            for p in positions:
                await self.live_engine.cancel_all_orders(p['symbol'])

    async def execute_signal(self, signal: Signal, neutral_grid=None, trend_dca=None):
        """
        Executes the signal using the current mode.
        Returns the order response dict or None on failure.
        """
        symbol = signal.symbol

        # 1. CORE RISK ENGINE VALIDATION (HARD BLOCK)
        if self.risk_engine.should_shutdown():
            logger.critical("[Router] HARD KILL SWITCH TRIGGERED: Global risk limits breached. Cancelling all orders & closing positions.")
            await self.close_all_positions()
            return None

        if not self.risk_engine.validate_order(signal):
            logger.error(f"[Router] Order for {symbol} rejected by CoreRiskEngine constraints.")
            return None

        # Apply Advanced Liquidity Sizing globally across all modes
        original_amount = signal.amount
        allowed_amount, mid_price = await self.calculate_liquidity_sizing(symbol, signal)
        
        if allowed_amount <= 0:
            logger.warning(f"[Router] Signal for {symbol} BLOCKED: Zero Liquid Volume.")
            return None
            
        if allowed_amount < original_amount:
            logger.info(f"[Router] Liquid Sizing {symbol}: {original_amount:.4f} -> {allowed_amount:.4f}")
            signal.amount = allowed_amount

        # Validate order constraints (e.g., Min Notional, Price Bounds)
        signal = OrderValidator.validate_signal(signal, mid_price, self.config)
        if not signal:
            return None

        if self.mode == 'SHADOW':
            order_res = self.shadow_executor.execute_signal(signal)
            logger.info(f"[Router] SHADOW: Executed {signal.action.value} {symbol}")
            return order_res

        elif self.mode == 'PAPER':
            self.paper_manager.execute_signal(signal)
            logger.info(f"[Router] PAPER: Executed {signal.action.value} {symbol}")
            return {"id": "PAPER_ORDER", "status": "closed"}

        else:
            # LIVE
            order_res = None
            if signal.action == SignalAction.GRID_PLACE:
                order_res = await self.live_engine.place_order(symbol, signal.side.name.lower(), 'limit', signal.amount, signal.price)
                if order_res and order_res.get('id') and neutral_grid:
                    neutral_grid.update_order_id(symbol, signal.price, order_res['id'])
            
            elif signal.action in [SignalAction.ENTER_LONG, SignalAction.ENTER_SHORT]:
                order_res = await self.live_engine.place_order(symbol, signal.side.name.lower(), 'market', signal.amount)
                # Side orders (SL/TP/DCA)
                if order_res and order_res.get('id'):
                    if getattr(signal, 'stop_loss', None):
                        sl_side = 'sell' if signal.side == Side.LONG else 'buy'
                        await self.live_engine.place_order(symbol, sl_side, 'stop', signal.amount, signal.stop_loss, params={'stopPrice': signal.stop_loss, 'reduceOnly': True})
                    if getattr(signal, 'take_profit', None):
                        tp_side = 'sell' if signal.side == Side.LONG else 'buy'
                        await self.live_engine.place_order(symbol, tp_side, 'limit', signal.amount, signal.take_profit, params={'reduceOnly': True})
                    
                    dca_levels_meta = signal.meta.get('dca_levels', [])
                    for dca_m in dca_levels_meta:
                        dca_order = await self.live_engine.place_order(symbol, signal.side.name.lower(), 'limit', dca_m['amount'], dca_m['price'])
                        if dca_order and dca_order.get('id') and trend_dca:
                            trend_dca.update_order_id(symbol, dca_m['price'], dca_order['id'])

            elif signal.action in [SignalAction.EXIT_LONG, SignalAction.EXIT_SHORT]:
                order_res = await self.live_engine.place_order(symbol, 'sell' if signal.side == Side.LONG else 'buy', 'market', signal.amount, params={'reduceOnly': True})

            return order_res
