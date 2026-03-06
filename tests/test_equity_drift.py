
import asyncio
import sys
import os
import logging
from unittest.mock import MagicMock

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from risk.risk_manager import RiskManager
from config.config_loader import Config

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("EquityTest")

async def test_equity_drift():
    logger.info("Starting Equity Drift Verification...")
    
    config = Config()
    config.EQUITY_DRIF_THRESHOLD = 0.05 # 5%
    rm = RiskManager(config)
    
    # 1. Initialize reference
    rm.sync_reference_equity(10000.0, 0.0)
    assert rm.reference_equity == 10000.0
    assert rm.is_safe_mode is False
    logger.info("Reference synchronized at 10000.0")
    
    # 2. Minor change (within 5%)
    drift_alert, val = rm.sync_reference_equity(10400.0, 0.0) # 4% increase
    assert rm.is_safe_mode is False
    assert drift_alert is False
    logger.info(f"Minor drift (4%) ignored as expected. Safe Mode: {rm.is_safe_mode}")
    
    # 3. Major drift (10% increase)
    drift_alert, val = rm.sync_reference_equity(11500.0, 0.0)
    assert rm.is_safe_mode is True
    assert drift_alert is True
    logger.info(f"Major drift detected (10%). Safe Mode: {rm.is_safe_mode}")
    
    # 4. Verify size calculation is blocked in Safe Mode
    size = rm.calculate_position_size("BTC/USDT", 60000.0, 59000.0)
    assert size == 0.0
    logger.info("Size calculation blocked in Safe Mode as expected.")
    
    # 5. Test Invalid Equity (<= 0)
    rm.is_safe_mode = False # Reset
    rm.sync_reference_equity(0.0, 0.0)
    assert rm.is_safe_mode is True
    logger.info("Invalid equity (0.0) triggered Safe Mode.")

    logger.info("Equity Drift Verification Complete!")

if __name__ == "__main__":
    asyncio.run(test_equity_drift())
