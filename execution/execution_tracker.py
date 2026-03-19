import logging
from enum import Enum

logger = logging.getLogger(__name__)

class OrderState(Enum):
    PENDING = 'pending'
    SENT = 'sent'
    FILLED = 'filled'
    FAILED = 'failed'

class ExecutionTracker:
    """
    Idempotency layer tracking UUID sequences to categorically reject duplicate executions.
    """
    def __init__(self):
        # In memory tracker. A production system aligns this directly with StateStore.
        self.orders = {}
        self.retries = {}

    def register(self, order_id: str) -> bool:
        if order_id not in self.orders:
            self.orders[order_id] = OrderState.PENDING
            self.retries[order_id] = 0
            return True
        return False

    def already_executed(self, order_id: str) -> bool:
        """Helper for checking absolute finality if needed externally"""
        if order_id in self.orders:
            state = self.orders[order_id]
            if state in [OrderState.SENT, OrderState.FILLED]:
                return True
        return False

    def update_status(self, order_id: str, status: OrderState):
        self.orders[order_id] = status
        from state.state_store import StateStore
        StateStore().save_order(order_id, status.value)

    def increment_retry(self, order_id: str):
        self.retries[order_id] = self.retries.get(order_id, 0) + 1
