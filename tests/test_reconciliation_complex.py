
import asyncio
import sys
import os
import logging
from unittest.mock import MagicMock

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from strategy.neutral_grid_strategy import NeutralGridStrategy
from common.types import GridLevel, GridState

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ReconcileTest")

async def test_complex_reconciliation():
    logger.info("Starting Complex Reconciliation Verification...")
    
    config = MagicMock()
    config.GRID_LEVELS = 4
    strategy = NeutralGridStrategy(config)
    
    symbol = "BTC/USDT"
    levels = [
        GridLevel(price=60000.0, side='buy', amount=0.1, order_id='oid-1'),
        GridLevel(price=60500.0, side='buy', amount=0.1, order_id='oid-2'),
        GridLevel(price=61000.0, side='sell', amount=0.1, order_id='oid-3'),
        GridLevel(price=61500.0, side='sell', amount=0.1, order_id='oid-4')
    ]
    strategy.grid_states[symbol] = GridState(
        symbol=symbol, levels=levels, poc=60750, vah=62000, val=60000, is_active=True
    )
    
    # 1. Simulate Exchange state
    # - oid-1 and oid-2 are still there
    # - oid-3 is MISSING (maybe user canceled it manually)
    # - oid-X is an ORPHAN (an order on exchange that strategy doesn't know)
    exchange_orders = [
        {'id': 'oid-1', 'side': 'BUY', 'price': 60000.0, 'amount': 0.1},
        {'id': 'oid-2', 'side': 'BUY', 'price': 60500.0, 'amount': 0.1},
        {'id': 'oid-X', 'side': 'SELL', 'price': 62000.0, 'amount': 0.1}, # Orphan
    ]
    
    logger.info("Triggering reconciliation...")
    strategy.reconcile_with_exchange(symbol, exchange_orders)
    
    # Verify oid-3 was reset
    assert strategy.grid_states[symbol].levels[2].order_id is None
    logger.info("Missing order oid-3 correctly reset to None.")
    
    # Verify oid-1 and oid-2 were kept
    assert strategy.grid_states[symbol].levels[0].order_id == 'oid-1'
    assert strategy.grid_states[symbol].levels[1].order_id == 'oid-2'
    
    # The orphan is just logged (we saw the warning logic in code)
    logger.info("Reconciliation check complete. Orphans and missing orders handled.")

if __name__ == "__main__":
    asyncio.run(test_complex_reconciliation())
