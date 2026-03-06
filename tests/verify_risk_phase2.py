
import asyncio
import sys
import os
import json
import logging
from datetime import date

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from risk.risk_manager import RiskManager
from config.config_loader import Config

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("Phase2Test")

async def test_risk_phase2():
    logger.info("Starting Phase 2 Risk Verification...")
    
    state_file = "risk_state.json"
    if os.path.exists(state_file):
        os.remove(state_file)
        
    # 1. Test Persistence of day_start_equity
    logger.info("--- Testing Persistence ---")
    risk1 = RiskManager(Config)
    risk1.sync_reference_equity(10000.0, 0.0)
    risk1.check_daily_drawdown(-2000.0, 10000.0) # Triggering drawdown (assuming 10% limit)
    # If DAILY_LOSS_LIMIT is 0.1, 2000 loss > 1000 limit. Kill switch should trigger.
    
    assert risk1.is_kill_switch_active == True
    risk1.save_state()
    
    # Simulate restart
    risk2 = RiskManager(Config)
    logger.info(f"Loaded Kill Switch State: {risk2.is_kill_switch_active}")
    assert risk2.is_kill_switch_active == True
    assert risk2.day_start_equity == 10000.0
    
    # 2. Test Alert Throttling
    logger.info("--- Testing Alert Throttling ---")
    risk2.alert_throttle_seconds = 2 # Set small for test
    risk2.last_kill_switch_alert = 0
    
    triggered = risk2._throttle_alert("Test Alert 1")
    assert triggered == True
    
    triggered_spam = risk2._throttle_alert("Test Alert 2")
    assert triggered_spam == False # throttled
    
    logger.info("Waiting for throttle...")
    await asyncio.sleep(2.1)
    
    triggered_new = risk2._throttle_alert("Test Alert 3")
    assert triggered_new == True # should pass now
    
    # 3. Test Daily Reset
    logger.info("--- Testing Daily Reset ---")
    # Mock date to tomorrow
    risk2.last_reset_date = date.fromisoformat("2020-01-01") # yesterday
    risk2._check_daily_reset(current_equity=12000.0)
    
    assert risk2.is_kill_switch_active == False
    assert risk2.day_start_equity == 12000.0
    assert risk2.daily_pnl == 0.0
    
    logger.info("Phase 2 Verification Successful!")

if __name__ == "__main__":
    asyncio.run(test_risk_phase2())
