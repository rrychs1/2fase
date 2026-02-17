import pandas as pd
import numpy as np
import logging
from common.types import Side, SignalAction, Signal, GridLevel, GridState, VolumeProfile
from typing import List

logger = logging.getLogger(__name__)

class NeutralGridStrategy:
    def __init__(self, config):
        self.config = config
        self.grid_states: dict[str, GridState] = {} # symbol -> GridState

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
        elif current_price > vp.vah or current_price < vp.val:
            # Price escaped the value area
            logger.info(f"[Grid] {symbol} Price {current_price:.2f} outside Value Area ({vp.val:.2f} - {vp.vah:.2f}). Rebuild needed.")
            rebuild_needed = True

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
            for level in state.levels:
                if not level.filled:
                    if (level.side == 'buy' and current_price <= level.price) or \
                       (level.side == 'sell' and current_price >= level.price):
                        level.filled = True
                        logger.info(f"[Grid] {symbol} Level {level.price} ({level.side}) FILLED. Replenishing...")
                        
                        opposite_side = 'sell' if level.side == 'buy' else 'buy'
                        signals.append(Signal(
                            symbol=symbol,
                            action=SignalAction.GRID_PLACE,
                            side=Side.SHORT if opposite_side == 'sell' else Side.LONG,
                            price=level.price,
                            amount=level.amount,
                            strategy="GridReplenish"
                        ))

        return signals
