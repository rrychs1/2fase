import logging
from enum import Enum

logger = logging.getLogger(__name__)


class OrderState(Enum):
    PENDING = "pending"
    SENT = "sent"
    FILLED = "filled"
    FAILED = "failed"


class ExecutionTracker:
    """
    Idempotency layer tracking UUID sequences to categorically reject duplicate executions.

    C-05 fix: On init, re-hydrates self.orders from StateStore so that orders persisted
    as PENDING in a previous run are visible after a restart.  This prevents the bot from
    treating them as new UUIDs and executing them a second time.

    Orphaned PENDINGs (written to DB but never sent to exchange) are surfaced so callers
    can decide to mark them FAILED before retrying.
    """

    def __init__(self):
        # In-memory tracker.  Populated from StateStore on startup.
        self.orders: dict = {}
        self.retries: dict = {}
        self._rehydrate_from_store()

    def _rehydrate_from_store(self):
        """
        C-05: Load non-FAILED order states from the durable StateStore into memory
        so that idempotency survives process restarts.
        """
        try:
            from state.state_store import StateStore
            store = StateStore()
            persisted = store.load_all_orders()  # {order_id: status_str}
            for order_id, status_str in persisted.items():
                try:
                    state = OrderState(status_str)
                    if state != OrderState.FAILED:
                        self.orders[order_id] = state
                        self.retries[order_id] = 0
                except ValueError:
                    pass  # unknown state value — skip
            if self.orders:
                logger.info(
                    "[ExecutionTracker] Re-hydrated %d in-flight order(s) from StateStore.",
                    len(self.orders),
                )
        except Exception as e:
            logger.warning(
                "[ExecutionTracker] Could not re-hydrate from StateStore: %s. "
                "Idempotency is in-memory only for this session.",
                e,
            )

    def get_orphaned_pending(self) -> list:
        """
        C-05: Returns order IDs that are PENDING in memory (loaded from a previous run)
        but were never confirmed sent.  Callers should mark these FAILED before trading.
        """
        return [
            oid
            for oid, state in self.orders.items()
            if state == OrderState.PENDING
        ]

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
