import asyncio
import sys
import os
import logging

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from exchange.exchange_client import ExchangeClient
from risk.risk_manager import RiskManager
from config.config_loader import Config

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("AuditTest")


async def test_audit_filters():
    logger.info("Starting Audit Filters Verification...")

    # 1. Setup Mock Exchange with limited filters
    client = ExchangeClient()
    # Manually inject a market with filters
    client.exchange.markets = {
        "BTC/USDT": {
            "symbol": "BTC/USDT",
            "limits": {
                "amount": {"min": 0.001, "step": 0.001},
                "cost": {"min": 100.0},  # 100 USDT min notional for test
            },
        }
    }

    risk = RiskManager(Config)

    # 2. Test Safe Mode with 0 Equity
    logger.info("--- Testing Safe Mode ---")
    risk.sync_reference_equity(0, 0)
    size = risk.calculate_position_size("BTC/USDT", 60000, 59000, client)
    logger.info(f"Size with 0 equity: {size} (Expected: 0.0)")
    assert size == 0.0
    assert risk.is_safe_mode == True

    # 3. Test Recovery and Min Notional
    logger.info("--- Testing Min Notional ---")
    risk.sync_reference_equity(1000, 0)  # 1000 USDT equity
    assert risk.is_safe_mode == False

    # Case: Risk amount is small, leading to small size
    # Risk per trade is usually 0.01 (1%) -> 10 USDT risk
    # At 60k entry, 59k SL (1k risk per unit), size = 10 / 1000 = 0.01
    # Cost = 0.01 * 60000 = 600 USDT. This should PASS > 100.
    size = risk.calculate_position_size(
        "BTC/USDT", 60000, 59900, client
    )  # 100$ per unit risk
    # Size = 10 / 100 = 0.1. Cost = 0.1 * 60000 = 6000. PASS.
    logger.info(f"Size for valid order: {size}")
    assert size > 0

    # Case: Very tight SL or low risk leading to small notional
    # Let's mock a case where risk amount is tiny
    risk.sync_reference_equity(100, 0)  # 100$ equity -> 1$ risk
    # entry 60000, SL 59999 (1$ risk per unit) -> size 1
    # Cost = 1 * 60000 = 60000. Still PASS.

    # Let's mock a case where cost is small
    # Entry 100, SL 90 (10 risk per unit) -> size = 1 / 10 = 0.1
    # Cost = 0.1 * 100 = 10. This should FAIL < 100 min notional.
    size = risk.calculate_position_size("BTC/USDT", 100, 90, client)
    logger.info(f"Size for small notional (<100): {size} (Expected: 0.0)")
    assert size == 0.0

    logger.info("Verification Successful!")


if __name__ == "__main__":
    asyncio.run(test_audit_filters())
