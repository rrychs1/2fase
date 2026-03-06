
import asyncio
import sys
import os
import logging
import json
from unittest.mock import MagicMock

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from risk.risk_manager import RiskManager
from config.config_loader import Config

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ShutdownTest")

async def test_shutdown_persistence():
    logger.info("Starting Shutdown & Persistence Verification...")
    
    config = Config()
    rm = RiskManager(config)
    rm.state_file = "test_risk_state.json"
    if os.path.exists(rm.state_file): os.remove(rm.state_file)
    
    # 1. Modify state and save
    rm.day_start_equity = 5000.0
    rm.is_kill_switch_active = True
    rm.save_state()
    logger.info("State saved to test_risk_state.json")
    
    # 2. Re-initialize and load
    rm2 = RiskManager(config)
    rm2.state_file = "test_risk_state.json"
    rm2.load_state()
    
    assert rm2.day_start_equity == 5000.0
    assert rm2.is_kill_switch_active is True
    logger.info("State correctly reloaded after 'shutdown' simulation.")
    
    # 3. Verify finally block simulation (connections)
    # This is more of a code review Check: BotRunner.run uses finally: self.exchange.close()
    
    # Cleanup
    if os.path.exists(rm.state_file): os.remove(rm.state_file)
    
    logger.info("Shutdown & Persistence Verification Complete!")

if __name__ == "__main__":
    asyncio.run(test_shutdown_persistence())
