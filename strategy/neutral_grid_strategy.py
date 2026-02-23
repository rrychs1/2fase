import pandas as pd
import numpy as np
import logging
import time
from common.types import Side, SignalAction, Signal, GridLevel, GridState, VolumeProfile
from typing import List

logger = logging.getLogger(__name__)

class NeutralGridStrategy:
    def __init__(self, config):
        self.config = config
        self.grid_states: dict[str, GridState] = {} # symbol -> GridState
        self.last_rebuild_time: dict[str, float] = {}
        self.consecutive_outside: dict[str, int] = {}

    def generate_grid_levels(self, symbol: str, vp: VolumeProfile, total_amount: float) -> List[GridLevel]:
        """
        Creates grid levels based on Value Area and POC.
        Buys between VAL and POC, Sells between POC and VAH.
        """
        num_levels = self.config.GRID_LEVELS
        buy_prices = np.linspace(vp.val, vp.poc, num_levels // 2 + 1)[:-1] # Exclude POC
        sell_prices = np.linspace(vp.poc, vp.vah, num_levels // 2 + 1)[1:]  # Exclude POC
        
        levels = []
        amount_per_level = total_amount / num_levels
        
        for p in buy_prices:
            price = float(p)
            levels.append(GridLevel(price=price, side='buy', amount=amount_per_level / price))
        for p in sell_prices:
            price = float(p)
            levels.append(GridLevel(price=price, side='sell', amount=amount_per_level / price))
            
        logger.info(f"[Grid] {symbol} Generated {len(levels)} levels around POC {vp.poc:.2f}")
        return levels

    async def on_market_state(self, symbol: str, market_state: dict) -> List[Signal]:
        """
        Evaluate if we need to place a new grid or manage existing orders.
        """
        current_price = market_state['price']
        vp = market_state.get('volume_profile')
        position_state = market_state.get('position')
        
        logger.debug(f"[Grid] {symbol} Price: {current_price}")
        signals = []
        
        # 1. Check if we need to initialize or rebuild the grid
        state = self.grid_states.get(symbol)
        
        rebuild_needed = False
        if not state or not state.is_active:
            rebuild_needed = True
            self.consecutive_outside[symbol] = 0
        elif current_price > vp.vah or current_price < vp.val:
            # Track consecutive out-of-range checks
            self.consecutive_outside[symbol] = self.consecutive_outside.get(symbol, 0) + 1
            
            if self.consecutive_outside[symbol] >= 2:
                # Check cooldown (10 minutes)
                now = time.time()
                last_rebuild = self.last_rebuild_time.get(symbol, 0)
                if now - last_rebuild > 600:  # 10 min cooldown
                    logger.info(f"[Grid] {symbol} Price {current_price:.2f} outside Value Area "
                               f"({vp.val:.2f} - {vp.vah:.2f}) for {self.consecutive_outside[symbol]} checks. Rebuilding.")
                    rebuild_needed = True
                else:
                    remaining = int(600 - (now - last_rebuild))
                    logger.info(f"[Grid] {symbol} Rebuild on cooldown ({remaining}s remaining)")
            else:
                logger.info(f"[Grid] {symbol} Price outside VA ({self.consecutive_outside[symbol]}/2 checks)")
        else:
            # Price is back inside Value Area, reset counter
            self.consecutive_outside[symbol] = 0

        if rebuild_needed:
            # Logic to cancel old grid and place new one
            equity = market_state.get('equity', 10000.0)
            grid_budget = equity * 0.40 # Higher allocation for testnet notional compliance
            
            new_levels = self.generate_grid_levels(symbol, vp, grid_budget) 
            self.grid_states[symbol] = GridState(
                symbol=symbol,
                levels=new_levels,
                poc=vp.poc, vah=vp.vah, val=vp.val, is_active=True
            )
            self.last_rebuild_time[symbol] = time.time()
            self.consecutive_outside[symbol] = 0
            
            # Emit signals for all new levels
            for level in new_levels:
                signals.append(Signal(
                    symbol=symbol,
                    action=SignalAction.GRID_PLACE,
                    side=Side.LONG if level.side == 'buy' else Side.SHORT,
                    price=level.price,
                    amount=level.amount,
                    strategy="GridInitial",
                    confidence=0.9
                ))
        else:
            # 2. Check for level crossings to "replenish" the grid
            if state and state.levels:
                for level in state.levels:
                    if not level.filled:
                        if (level.side == 'buy' and current_price <= level.price) or \
                           (level.side == 'sell' and current_price >= level.price):
                            level.filled = True
                            logger.info(f"[Grid] {symbol} Level {level.price} ({level.side}) FILLED. Replenishing...")
                            
                            signals.append(Signal(
                                symbol=symbol,
                                action=SignalAction.GRID_PLACE,
                                side=Side.SHORT if opposite_side == 'sell' else Side.LONG,
                                price=level.price,
                                amount=level.amount,
                                strategy="GridReplenish"
                            ))

    def reconcile_with_exchange(self, symbol: str, open_orders: List[dict]):
        """
        Synchronizes internal grid state with active exchange orders.
        Detects orphaned orders and missing levels.
        """
        state = self.grid_states.get(symbol)
        if not state or not state.is_active:
            return

        order_ids_on_exchange = {str(o['id']) for o in open_orders}
        
        for level in state.levels:
            if level.order_id:
                if level.order_id not in order_ids_on_exchange:
                    if not level.filled:
                        logger.warning(f"[Grid] {symbol} Order {level.order_id} missing on exchange but not marked filled. Resetting.")
                        level.order_id = None
                else:
                    # Order still active
                    pass
            elif not level.filled:
                # Level should have an order but order_id is missing (maybe failed to place)
                pass

        # Detect Orphans: orders on exchange that we don't recognize
        recognized_ids = {str(l.order_id) for l in state.levels if l.order_id}
        for o in open_orders:
            oid = str(o['id'])
            if oid not in recognized_ids:
                logger.warning(f"[Grid] {symbol} Orphaned order detected: {oid} {o['side']} @ {o['price']}. Recommended: Manual cancel or reconstruction.")

    def update_order_id(self, symbol: str, price: float, order_id: str):
        """Update the internal state with the real order ID from exchange."""
        state = self.grid_states.get(symbol)
        if state:
            for level in state.levels:
                if abs(level.price - price) / price < 0.0001: # Match by price proximity
                    level.order_id = str(order_id)
                    return

        return signals
