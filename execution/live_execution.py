import logging
from core.interfaces import ExecutionProvider

logger = logging.getLogger(__name__)


class LiveExecutionProvider(ExecutionProvider):
    """Real-World Execution pipeline securely bridging Core Strategy directly into Live Execution Engine."""

    def __init__(self, execution_engine):
        self.engine = execution_engine

    async def execute_order_safe(self, signal, order_type: str, params: dict = None):
        return await self.engine.execute_order_safe(signal, order_type, params)

    async def fetch_open_orders(self, symbol: str):
        return await self.engine.fetch_open_orders(symbol)

    async def cancel_all_orders(self, symbol: str):
        return await self.engine.cancel_all_orders(symbol)

    async def close_all_positions(self):
        return await self.engine.close_all_positions()
