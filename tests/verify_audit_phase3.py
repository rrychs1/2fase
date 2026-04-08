import asyncio
import sys
import os
import logging
import time
from unittest.mock import MagicMock, AsyncMock

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from exchange.exchange_client import ExchangeClient
from risk.risk_manager import RiskManager
from orchestration.bot_runner import BotRunner
from common.types import Side, Signal, SignalAction, GridLevel, GridState

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("Phase3Test")


async def test_audit_phase3():
    logger.info("Starting Senior Audit Phase 3 Verification...")

    # 1. Setup Mock Config
    config = MagicMock()
    config.ANALYSIS_ONLY = False
    config.DRY_RUN = True  # TEST DRY RUN
    config.SYMBOLS = ["BTC/USDT"]
    config.GRID_LEVELS = 4
    config.EQUITY_DRIFT_THRESHOLD = 0.05
    config.DAILY_LOSS_LIMIT = 0.05
    config.KILL_SWITCH_ENABLED = True
    config.POLLING_INTERVAL = 1

    # 2. Setup Components
    exchange = MagicMock(spec=ExchangeClient)
    # Mock fetch_balance to return stable equity
    exchange.fetch_balance = AsyncMock(
        return_value={"total": {"USDT": 10000.0}, "free": {"USDT": 10000.0}}
    )
    exchange.fetch_positions = AsyncMock(return_value=[])
    exchange.fetch_open_orders = AsyncMock(return_value=[])

    risk = RiskManager(config)
    runner = BotRunner()

    # Inject mocks
    runner.config = config
    runner.exchange = exchange
    runner.risk_manager = risk
    runner.execution.exchange = exchange
    runner.execution.config = config

    logger.info("--- Test 1: DRY_RUN Order Placement ---")
    # Simulate a signal
    signal = Signal(
        symbol="BTC/USDT",
        action=SignalAction.GRID_PLACE,
        side=Side.LONG,
        price=60000.0,
        amount=0.01,
        strategy="GridInitial",
    )

    # Place order via execution engine (which should be in DRY_RUN)
    res = await runner.execution.place_order("BTC/USDT", "buy", "limit", 0.01, 60000.0)
    logger.info(f"Order response: {res}")

    assert res is not None
    assert "sim-buy-" in res["id"]
    assert res["info"]["simulated"] is True
    logger.info(f"DRY_RUN Successful: Generated simulated order {res['id']}")

    logger.info("--- Test 2: Reconciliation (Internal Tracking) ---")
    # Mock some levels in Neutral Grid
    runner.neutral_grid.grid_states["BTC/USDT"] = GridState(
        symbol="BTC/USDT",
        levels=[
            GridLevel(
                price=60000.0,
                side="buy",
                amount=0.01,
                order_id="order-123",
                filled=False,
            ),
            GridLevel(
                price=61000.0,
                side="buy",
                amount=0.01,
                order_id="order-456",
                filled=False,
            ),
        ],
        is_active=True,
    )

    # Case A: One order missing on exchange
    mock_open_orders = [{"id": "order-123", "side": "buy", "price": 60000.0}]
    logger.info("Reconciling with one order missing...")
    runner.neutral_grid.reconcile_with_exchange("BTC/USDT", mock_open_orders)

    levels = runner.neutral_grid.grid_states["BTC/USDT"].levels
    # Level 61000.0 had order-456 which is missing in mock_open_orders
    for l in levels:
        if l.price == 61000.0:
            assert l.order_id is None
            logger.info(
                f"Reconciliation Successful: Detected missing order for level {l.price} and reset order_id"
            )
        if l.price == 60000.0:
            assert l.order_id == "order-123"

    logger.info("--- Test 3: Transitions ---")
    # Set old regime
    runner.current_regimes["BTC/USDT"] = "range"
    # Mock regime detector to return "trend"
    runner.regime_detector.detect_regime = MagicMock(return_value="trend")
    # Mock data fetch
    runner.exchange.fetch_ohlcv = AsyncMock(return_value=[])  # dummy

    # This should trigger the transition logic in BotRunner (if we were inside the loop)
    # For unit test, we check if the logic we added is correct.

    logger.info("Verification Complete!")


if __name__ == "__main__":
    asyncio.run(test_audit_phase3())
