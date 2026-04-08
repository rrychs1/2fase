import logging
import time
import uuid
import asyncio
from exchange.exchange_client import ExchangeClient
from config.config_loader import Config
from state.state_store import StateStore
from execution.execution_tracker import ExecutionTracker, OrderState
from monitoring.metrics import execution_latency_ms

logger = logging.getLogger(__name__)


class ExecutionEngine:
    def __init__(self, exchange_client: ExchangeClient, config: Config):
        self.exchange = exchange_client
        self.config = config
        self.state_store = StateStore()
        self.tracker = ExecutionTracker()

    async def execute_order_safe(
        self, signal, order_type: str, params: dict = None
    ) -> dict:
        """
        Idempotent wrapper executing the signal natively on the exchange API.
        Enforces UUID tracking, handles retries, and catches timeout faults safely.
        """
        if not getattr(signal, "order_id", None):
            signal.order_id = str(uuid.uuid4())

        order_id = signal.order_id

        # Atomically register execution. Returns False if already exists
        if not self.tracker.register(order_id):
            if self.tracker.orders.get(order_id) != OrderState.FAILED:
                logger.warning(
                    f"[Idempotency] Order {order_id} ({signal.symbol}) already executing/executed. Blocking duplicate."
                )
                return None

        max_retries = getattr(self.config, "MAX_ORDER_RETRIES", 3)
        base_backoff_sec = 1.0

        for attempt in range(max_retries + 1):
            try:
                self.tracker.update_status(order_id, OrderState.PENDING)

                side_str = (
                    signal.side.name.lower()
                    if hasattr(signal.side, "name")
                    else str(signal.side).lower()
                )

                # --- OBSERVABILITY LATENCY TELEMETRY TIMING BLOCK ---
                t_start = time.time()
                order_res = await self.place_order(
                    symbol=signal.symbol,
                    side=side_str,
                    type=order_type,
                    amount=signal.amount,
                    price=getattr(signal, "price", None),
                    params=params,
                )
                t_end = time.time()

                if not order_res:
                    raise Exception("Exchange returned empty object")

                latency_ms = (t_end - t_start) * 1000
                execution_latency_ms.observe(latency_ms)

                status = order_res.get("status", "unknown")
                if status == "closed" or status == "filled":
                    self.tracker.update_status(order_id, OrderState.FILLED)
                    logger.info(
                        f"Order FILLED natively",
                        extra={
                            "event": "OrderFilled",
                            "symbol": signal.symbol,
                            "latency_ms": latency_ms,
                            "pnl": 0.0,
                            "amount": signal.amount,
                        },
                    )
                elif status == "open":
                    self.tracker.update_status(order_id, OrderState.SENT)
                    logger.info(
                        f"Order ROUTED natively",
                        extra={
                            "event": "OrderSent",
                            "symbol": signal.symbol,
                            "latency_ms": latency_ms,
                        },
                    )
                else:
                    self.tracker.update_status(order_id, OrderState.FAILED)

                return order_res

            except Exception as e:
                err_str = str(e).lower()
                is_timeout = (
                    "timeout" in err_str or "502" in err_str or "network" in err_str
                )

                if is_timeout and attempt < max_retries:
                    logger.warning(
                        f"[Retry] Network/Timeout error on {order_id}. Retrying {attempt+1}/{max_retries}...",
                        extra={"event": "OrderRetry", "symbol": signal.symbol},
                    )
                    self.tracker.increment_retry(order_id)
                    await asyncio.sleep(base_backoff_sec * (2**attempt))
                    continue
                else:
                    self.tracker.update_status(order_id, OrderState.FAILED)
                    logger.error(
                        f"[EXEC] Order Final Failure {order_id}: {e}",
                        extra={"event": "OrderFailed", "symbol": signal.symbol},
                    )
                    return None

        return None

    async def sync_state_on_startup(self):
        """
        FAILSAFE SYNC: Reconciles Live Exchange state against Local StateStore.
        If a severe mismatch is detected, triggers a panic halt.
        """
        if getattr(self.config, "EXECUTION_MODE", "PAPER") != "LIVE":
            return True

        logger.info(
            "[Sync] Synchronizing real exchange state against local StateStore..."
        )
        live_positions = await self.fetch_positions()
        local_positions = self.state_store.load_positions()

        mismatch_detected = False

        # 1. Verification of Local vs Live
        for p in live_positions:
            sym = p["symbol"]
            live_amt = abs(float(p["contracts"]))
            if sym not in local_positions:
                logger.critical(
                    f"[FAILSAFE] State Mismatch: Exchange has {sym} ({live_amt}), but local DB has none!"
                )
                mismatch_detected = True
            else:
                local_amt = local_positions[sym]["amount"]
                # Sub-precision mismatch tolerance
                if abs(live_amt - local_amt) > 0.001:
                    logger.critical(
                        f"[FAILSAFE] Mismatch on {sym}: Exchange ({live_amt}) vs Local ({local_amt})"
                    )
                    mismatch_detected = True

        # 2. Orphans in Local DB
        live_symbols = [p["symbol"] for p in live_positions]
        for sym in local_positions:
            if sym not in live_symbols:
                logger.critical(
                    f"[FAILSAFE] State Mismatch: Local DB tracks {sym}, but Exchange does not have it!"
                )
                mismatch_detected = True

        if mismatch_detected:
            logger.critical(
                "[FAILSAFE] TRADING PAUSED. Manual state reconciliation required. Unsafe to proceed.",
                extra={"event": "StateMismatchHalt"},
            )
            # Hard crash to prevent corrupt trading loops and runaway cascading risk triggers
            import sys

            sys.exit(1)

        logger.info(
            "[Sync] State reconciliation complete. DB exactly matches Exchange."
        )
        return True

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
            if p["symbol"] == symbol:
                side = "LONG" if float(p["contracts"]) > 0 else "SHORT"
                return {
                    "symbol": symbol,
                    "side": side,
                    "is_active": True,
                    "entry_price": float(p.get("entryPrice", 0)),
                    "average_price": float(p.get("entryPrice", 0)),
                    "amount": abs(float(p["contracts"])),
                    "unrealized_pnl": float(p.get("unrealizedPnl", 0)),
                }
        return {}

    async def get_account_pnl(self):
        """Calculates total unrealized PnL from all open positions."""
        positions = await self.fetch_positions()
        total_pnl = sum(float(p.get("unrealizedPnl", 0.0)) for p in positions)
        return total_pnl

    async def place_order(self, symbol, side, type, amount, price=None, params=None):
        """
        Placing orders with precision enforcement.
        Supports: 'limit', 'market', and 'stop' (via params)
        """
        if getattr(self.config, "ANALYSIS_ONLY", False) or getattr(
            self.config, "DRY_RUN", False
        ):
            mode = (
                "ANALYSIS_ONLY"
                if getattr(self.config, "ANALYSIS_ONLY", False)
                else "DRY_RUN"
            )
            logger.info(
                f"[EXEC] {mode}: Simulation of {side} {type} {symbol} {amount} @ {price}"
            )
            return {
                "id": f"sim-{side}-{int(time.time())}",
                "status": "open",
                "info": {"simulated": True},
            }

        try:
            # Delegate to Unified Exchange Client
            return await self.exchange.create_order(
                symbol, type, side, amount, price, params
            )

        except Exception as e:
            logger.error(f"[EXEC] Order Placement Failed for {symbol}: {e}")
            raise e

    async def cancel_all_orders(self, symbol: str):
        """Cancel all open orders for a specific symbol."""
        if getattr(self.config, "ANALYSIS_ONLY", False):
            logger.info(f"[EXEC] ANALYSIS_ONLY: Cancelling all orders for {symbol}")
            return
        try:
            return await self.exchange.cancel_all_orders(symbol)
        except Exception as e:
            logger.error(f"[EXEC] Error cancelling orders: {e}")

    async def close_all_positions(self):
        """Emergency method: close all active positions at market price."""
        if getattr(self.config, "ANALYSIS_ONLY", False):
            logger.info(
                "[EXEC] ANALYSIS_ONLY: Emergency Close All triggered (Simulated)"
            )
            return

        positions = await self.fetch_positions()
        for p in positions:
            symbol = p["symbol"]
            side = "sell" if float(p["contracts"]) > 0 else "buy"
            amount = abs(float(p["contracts"]))
            logger.warning(
                f"[EXEC] EMERGENCY CLOSE: {side} {amount} {symbol}",
                extra={"event": "EmergencyCloseAll", "symbol": symbol},
            )
            await self.place_order(symbol, side, "market", amount)
