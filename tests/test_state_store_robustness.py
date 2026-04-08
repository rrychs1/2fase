import pytest
import asyncio
import os
import threading
import concurrent.futures
import tempfile
import sqlite3
from unittest.mock import AsyncMock, patch
from state.state_store import StateStore
from execution.execution_engine import ExecutionEngine
from config.config_loader import Config


@pytest.fixture
def temp_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    yield path
    try:
        os.remove(path)
    except OSError:
        pass


class TestStateStoreRobustness:

    # ------------------------------------------------------------------------- #
    # A. Crash Recovery
    # ------------------------------------------------------------------------- #
    def test_crash_recovery(self, temp_db):
        """Simulates a hard crash after writing, ensuring exact data remains on disk."""
        # 1. Initialize and write
        store1 = StateStore(db_path=temp_db)
        store1.save_balance(10000.50)
        store1.save_position("BTC/USDT", 1.5, 60000.0)
        store1.save_position("ETH/USDT", 20.0, 3000.0)
        store1.save_order("ORD-1", "PENDING")

        # 2. Simulate Crash (destroy object in memory)
        del store1

        # 3. Reload from disk
        store2 = StateStore(db_path=temp_db)

        # 4. Verify exact consistency
        assert store2.get_balance() == 10000.50

        positions = store2.load_positions()
        assert "BTC/USDT" in positions
        assert positions["BTC/USDT"]["amount"] == 1.5
        assert positions["BTC/USDT"]["entry_price"] == 60000.0

        assert "ETH/USDT" in positions
        assert positions["ETH/USDT"]["amount"] == 20.0
        assert positions["ETH/USDT"]["entry_price"] == 3000.0

        orders = store2.get_open_orders()
        assert len(orders) == 1
        assert orders[0]["order_id"] == "ORD-1"
        assert orders[0]["status"] == "PENDING"

    # ------------------------------------------------------------------------- #
    # B. Concurrent access
    # ------------------------------------------------------------------------- #
    def test_concurrent_access_no_corruption(self, temp_db):
        """Spawns multiple threads thrashing the DB concurrently to ensure Locks hold."""
        store = StateStore(db_path=temp_db)

        def worker_task(worker_id):
            # Each worker saves its own symbol 100 times, updating the price
            for i in range(100):
                store.save_position(f"SYM-{worker_id}", 1.0, float(i))
                store.save_balance(1000.0 + worker_id)  # Thrash balance writes

        num_workers = 20
        with concurrent.futures.ThreadPoolExecutor(max_workers=num_workers) as executor:
            futures = [executor.submit(worker_task, w) for w in range(num_workers)]
            concurrent.futures.wait(futures)

        # Verify no corruption and final states are intact
        positions = store.load_positions()
        assert len(positions) == num_workers
        for w in range(num_workers):
            # Final price should be 99.0
            assert positions[f"SYM-{w}"]["entry_price"] == 99.0

    # ------------------------------------------------------------------------- #
    # D. Partial Write Failure / Lock Release
    # ------------------------------------------------------------------------- #
    def test_partial_write_failure_releases_lock(self, temp_db):
        """Interrupts write mid-operation to ensure DB isn't corrupted and thread locks release."""
        store = StateStore(db_path=temp_db)
        store.save_balance(5000.0)

        # We forcibly monkeypatch sqlite3 connect to raise an exception
        # specifically when saving a position to simulate an I/O crash.
        original_connect = sqlite3.connect

        def mock_connect(*args, **kwargs):
            raise sqlite3.OperationalError("Simulated Disk I/O Failure")

        with patch("sqlite3.connect", side_effect=mock_connect):
            with pytest.raises(sqlite3.OperationalError):
                store.save_position("BTC/USDT", 999.0, 999.0)

        # If the lock wasn't released inside the finally/context manager, the next call would deadlock.
        # It should succeed seamlessly.
        store.save_balance(6000.0)
        assert store.get_balance() == 6000.0

        # Position write should naturally be missing
        assert store.get_position("BTC/USDT") is None

    # ------------------------------------------------------------------------- #
    # STRESS TEST
    # ------------------------------------------------------------------------- #
    def test_stress_1000_rapid_updates(self, temp_db):
        """1,000 rapid sequential updates checking for data loss."""
        store = StateStore(db_path=temp_db)

        # We do this sequentially to maximize I/O bound stress testing without thread overhead masking it
        for i in range(1, 1001):
            store.save_position("BTC/USDT", float(i), 50000.0)

        final_pos = store.get_position("BTC/USDT")
        assert final_pos["amount"] == 1000.0


@pytest.mark.asyncio
class TestExchangeMismatchSimulation:
    # ------------------------------------------------------------------------- #
    # C. Exchange Mismatch Simulation
    # ------------------------------------------------------------------------- #
    async def test_startup_mismatch_pauses_trading(self, temp_db):
        """
        Simulates ExecutionEngine startup where Local StateStore != Remote Exchange.
        Ensures strict kill detection and SystemExit.
        """
        config = Config()
        config.EXECUTION_MODE = "LIVE"

        # 1. Prime the local DB with a position
        store = StateStore(db_path=temp_db)
        store.save_position("BTC/USDT", 2.0, 60000.0)

        # 2. Mock Exchange returning a DIFFERENT state (or empty)
        exchange_client = AsyncMock()
        exchange_client.fetch_positions = AsyncMock(
            return_value=[]
        )  # Exchange says we have 0 BTC

        # 3. Instantiate Engine
        engine = ExecutionEngine(exchange_client, config)
        engine.state_store = store  # Inject our explicit store

        # 4. Run Sync - EXPECT SystemExit or exception from the safety mismatch
        with pytest.raises(SystemExit) as excinfo:
            await engine.sync_state_on_startup()

        # Verify it raised a SystemExit / Mismatch detected
        assert excinfo.value.code == 1

    async def test_startup_match_allows_trading(self, temp_db):
        """
        Simulates ExecutionEngine startup where Local StateStore == Remote Exchange perfectly.
        Ensures execution is allowed to proceed smoothly.
        """
        config = Config()
        config.EXECUTION_MODE = "LIVE"

        store = StateStore(db_path=temp_db)
        store.save_position("BTC/USDT", 2.0, 60000.0)

        exchange_client = AsyncMock()
        exchange_client.fetch_positions = AsyncMock(
            return_value=[
                {"symbol": "BTC/USDT", "contracts": 2.0, "entryPrice": 60000.0}
            ]
        )

        engine = ExecutionEngine(exchange_client, config)
        engine.state_store = store

        # Should NOT raise SystemExit
        await engine.sync_state_on_startup()

        # Assert the sync succeeded transparently
        exchange_client.fetch_positions.assert_called_once()
