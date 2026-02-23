import logging
import time
from exchange.exchange_client import ExchangeClient
from config.config_loader import Config

logger = logging.getLogger(__name__)

class ExecutionEngine:
    def __init__(self, exchange_client: ExchangeClient, config: Config):
        self.exchange = exchange_client
        self.config = config

    async def fetch_open_orders(self, symbol: str = None):
        """Fetch all currently open orders from the exchange."""
        try:
            return await self.exchange.fetch_open_orders(symbol)
        except Exception as e:
            logger.error(f"Error fetching open orders: {e}")
            return []

    async def fetch_positions(self):
        """Fetch active positions with non-zero size."""
        try:
            return await self.exchange.fetch_positions()
        except Exception as e:
            logger.error(f"Error fetching positions: {e}")
            return []

    async def get_position(self, symbol: str) -> dict:
        """Returns normalized position info for a symbol or empty dict."""
        positions = await self.fetch_positions()
        for p in positions:
            if p['symbol'] == symbol:
                side = 'LONG' if float(p['contracts']) > 0 else 'SHORT'
                return {
                    'symbol': symbol,
                    'side': side,
                    'is_active': True,
                    'entry_price': float(p.get('entryPrice', 0)),
                    'average_price': float(p.get('entryPrice', 0)),
                    'amount': abs(float(p['contracts'])),
                    'unrealized_pnl': float(p.get('unrealizedPnl', 0))
                }
        return {}

    async def get_account_pnl(self):
        """Calculates total unrealized PnL from all open positions."""
        positions = await self.fetch_positions()
        total_pnl = sum(float(p.get('unrealizedPnl', 0.0)) for p in positions)
        return total_pnl

    async def place_order(self, symbol, side, type, amount, price=None, params=None):
        """
        Placing orders with precision enforcement.
        Supports: 'limit', 'market', and 'stop' (via params)
        """
        if getattr(self.config, 'ANALYSIS_ONLY', False) or getattr(self.config, 'DRY_RUN', False):
            mode = "ANALYSIS_ONLY" if getattr(self.config, 'ANALYSIS_ONLY', False) else "DRY_RUN"
            logger.info(f"[EXEC] {mode}: Simulation of {side} {type} {symbol} {amount} @ {price}")
            return {"id": f"sim-{side}-{int(time.time())}", "status": "open", "info": {"simulated": True}}
            
        try:
            # Delegate to Unified Exchange Client
            return await self.exchange.create_order(symbol, type, side, amount, price, params)
                
        except Exception as e:
            logger.error(f"[EXEC] Order Placement Failed for {symbol}: {e}")
            return None

    async def cancel_all_orders(self, symbol: str):
        """Cancel all open orders for a specific symbol."""
        if getattr(self.config, 'ANALYSIS_ONLY', False):
            logger.info(f"[EXEC] ANALYSIS_ONLY: Cancelling all orders for {symbol}")
            return
        try:
            return await self.exchange.cancel_all_orders(symbol)
        except Exception as e:
            logger.error(f"[EXEC] Error cancelling orders: {e}")

    async def close_all_positions(self):
        """Emergency method: close all active positions at market price."""
        if getattr(self.config, 'ANALYSIS_ONLY', False):
            logger.info("[EXEC] ANALYSIS_ONLY: Emergency Close All triggered (Simulated)")
            return
            
        positions = await self.fetch_positions()
        for p in positions:
            symbol = p['symbol']
            side = 'sell' if float(p['contracts']) > 0 else 'buy'
            amount = abs(float(p['contracts']))
            logger.warning(f"[EXEC] EMERGENCY CLOSE: {side} {amount} {symbol}")
            await self.place_order(symbol, side, 'market', amount)
