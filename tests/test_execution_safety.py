import pytest
import asyncio
from unittest.mock import AsyncMock, patch, MagicMock
from execution.execution_engine import ExecutionEngine
from execution.execution_tracker import ExecutionTracker, OrderState
from common.types import Signal, SignalAction, Side
from config.config_loader import Config


@pytest.fixture
def mock_config():
    cfg = Config()
    cfg.ANALYSIS_ONLY = False
    cfg.DRY_RUN = False
    cfg.MAX_ORDER_RETRIES = 3
    return cfg


@pytest.fixture
def mock_exchange():
    exchange = AsyncMock()
    return exchange


@pytest.fixture
def engine(mock_exchange, mock_config):
    # Overwrite state_store interactions just to test execution layer purely
    e = ExecutionEngine(mock_exchange, mock_config)
    e.state_store = MagicMock()
    return e


def create_signal(symbol="BTC/USDT", amount=1.0) -> Signal:
    import datetime, uuid

    sig = Signal(
        symbol=symbol,
        action=SignalAction.ENTER_LONG,
        side=Side.LONG,
        price=60000.0,
        amount=amount,
        strategy="TestMock",
        timestamp=datetime.datetime.now(datetime.timezone.utc),
    )
    sig.order_id = str(uuid.uuid4())
    return sig


class TestExecutionSafety:

    # ------------------------------------------------------------------------- #
    # 1. Duplicate order test
    # ------------------------------------------------------------------------- #
    @pytest.mark.asyncio
    async def test_duplicate_order_suppression(self, engine, mock_exchange):
        sig = create_signal()

        # Mock exchange success
        mock_exchange.create_order.return_value = {"id": "EXT-1", "status": "filled"}

        # First execution (should succeed)
        res1 = await engine.execute_order_safe(sig, "market")
        assert res1 is not None
        assert mock_exchange.create_order.call_count == 1

        # Second execution of the exact same signal/order_id
        res2 = await engine.execute_order_safe(sig, "market")
        # Should be blocked, returning None and NOT calling the exchange
        assert res2 is None
        assert mock_exchange.create_order.call_count == 1

    # ------------------------------------------------------------------------- #
    # 2. Retry test (Network Failure)
    # ------------------------------------------------------------------------- #
    @pytest.mark.asyncio
    async def test_network_retry_consistency(self, engine, mock_exchange):
        sig = create_signal()

        # Fail the first 2 times with a network error, succeed on the 3rd
        mock_exchange.create_order.side_effect = [
            Exception("502 Bad Gateway - Network Error"),
            Exception("ReadTimeout"),
            {"id": "EXT-2", "status": "filled"},
        ]

        # To avoid slowing down the test suite by waiting seconds for exponential backoff:
        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            res = await engine.execute_order_safe(sig, "market")

        assert res is not None
        assert res["id"] == "EXT-2"
        # Must have been called exactly 3 times
        assert mock_exchange.create_order.call_count == 3
        # Sleep called twice
        assert mock_sleep.call_count == 2

        # Finally, it should be marked as filled, not pending/failed
        assert engine.tracker.orders[sig.order_id] == OrderState.FILLED

    # ------------------------------------------------------------------------- #
    # 3. Partial fill test
    # ------------------------------------------------------------------------- #
    @pytest.mark.asyncio
    async def test_partial_fill_integrity(self, engine, mock_exchange):
        sig = create_signal(amount=10.0)

        # Return an open order that has been partially filled (e.g. 4.0 filled out of 10.0)
        mock_exchange.create_order.return_value = {
            "id": "EXT-3",
            "status": "open",
            "filled": 4.0,
            "remaining": 6.0,
        }

        res = await engine.execute_order_safe(sig, "limit")
        assert res is not None
        assert res["status"] == "open"
        assert res["filled"] == 4.0

        # Even if partially filled, idempotency layer should mark it as SENT so we don't accidentally resend the whole 10.0
        assert engine.tracker.orders[sig.order_id] == OrderState.SENT

        # If we try to send it again blindly, it must be rejected! No double counting.
        res2 = await engine.execute_order_safe(sig, "limit")
        assert res2 is None

    # ------------------------------------------------------------------------- #
    # 4. Timeout test (Aborts safely)
    # ------------------------------------------------------------------------- #
    @pytest.mark.asyncio
    async def test_timeout_aborts_eventually(self, engine, mock_exchange):
        sig = create_signal()

        # Exchange universally fails with timeout
        mock_exchange.create_order.side_effect = Exception("ConnectionTimeout")

        with patch("asyncio.sleep", new_callable=AsyncMock):
            res = await engine.execute_order_safe(sig, "market")

        # Should return None because all retries failed
        assert res is None
        # Max retries is 3. Attempt 0, 1, 2, 3 = 4 calls total.
        assert mock_exchange.create_order.call_count == 4
        # State should be securely failed so it doesn't leave phantom stuck states
        assert engine.tracker.orders[sig.order_id] == OrderState.FAILED

    # ------------------------------------------------------------------------- #
    # 5. Order rejection (No phantom state)
    # ------------------------------------------------------------------------- #
    @pytest.mark.asyncio
    async def test_order_rejection_no_phantom_position(self, engine, mock_exchange):
        sig = create_signal()

        # Exchange rejects immediately with a structural error (Not a network issue)
        mock_exchange.create_order.side_effect = ValueError("Insufficient Balance")

        res = await engine.execute_order_safe(sig, "market")

        assert res is None
        # Should NOT retry for non-network errors. Hard fail immediately.
        assert mock_exchange.create_order.call_count == 1
        assert engine.tracker.orders[sig.order_id] == OrderState.FAILED

    # ------------------------------------------------------------------------- #
    # 6. Race condition test
    # ------------------------------------------------------------------------- #
    @pytest.mark.asyncio
    async def test_simultaneous_race_condition(self, engine, mock_exchange):
        sig = create_signal()

        # We need `create_order` to simulate a tiny bit of latency to yield the event loop,
        # otherwise asyncio will process sequentially regardless of `gather`.
        async def mock_network_latency(*args, **kwargs):
            await asyncio.sleep(0.01)
            return {"id": "EXT-RACE", "status": "filled"}

        mock_exchange.create_order.side_effect = mock_network_latency

        # Submit the exact same signal 50 times simultaneously
        tasks = [engine.execute_order_safe(sig, "market") for _ in range(50)]
        results = await asyncio.gather(*tasks)

        # ONLY ONE execution should hit the mock exchange boundary.
        # This asserts idempotency locks cleanly around standard async yields.
        assert mock_exchange.create_order.call_count == 1

        # 1 success, 49 Nones
        successes = [r for r in results if r is not None]
        assert len(successes) == 1

        # Validate tracker state finalized cleanly
        assert engine.tracker.orders[sig.order_id] == OrderState.FILLED
