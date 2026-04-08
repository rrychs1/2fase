import logging
from core.interfaces import ExecutionProvider

logger = logging.getLogger(__name__)


class BacktestExecutionProvider(ExecutionProvider):
    """Simulates realistic Execution boundaries directly routing to Shadow Executor for fast-forward testing."""

    def __init__(self, shadow_executor):
        self.shadow = shadow_executor

    async def execute_order_safe(self, signal, order_type: str, params: dict = None):
        return self.shadow.process_signal(signal)

    async def fetch_open_orders(self, symbol: str):
        return []

    async def cancel_all_orders(self, symbol: str):
        pass

    async def close_all_positions(self):
        self.shadow.close_all_positions()
