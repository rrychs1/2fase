import asyncio
import pandas as pd
import numpy as np
import datetime
import logging
from unittest.mock import AsyncMock, MagicMock

from config.config_loader import Config
from orchestration.bot_runner import BotRunner
from analysis.evaluation_framework import StrategyEvaluator

def create_thirty_day_feed() -> pd.DataFrame:
    dates = pd.date_range(end=datetime.datetime.now(), periods=30 * 24, freq="1h")
    np.random.seed(42)
    returns = np.random.normal(loc=0.0001, scale=0.005, size=len(dates))
    price_path = np.exp(np.cumsum(returns)) * 50000.0
    
    df = pd.DataFrame({
        'timestamp': dates,
        'open': price_path,
        'high': price_path * (1 + np.abs(np.random.normal(0, 0.002, len(dates)))),
        'low': price_path * (1 - np.abs(np.random.normal(0, 0.002, len(dates)))),
        'close': price_path,
        'volume': np.random.uniform(10, 500, len(dates))
    })
    return df

async def main():
    print("Initializing Configuration...")
    config = Config()
    config.ANALYSIS_ONLY = False
    config.EXECUTION_MODE = 'PAPER'
    config.SYMBOLS = ["BTC/USDT"]
    config.TF_GRID = "1h"
    config.TF_TREND = "1h"
    config.CANDLES_ANALYSIS_LIMIT = 50
    config.SIMULATED_FEES_PCT = 0.001       
    config.SIMULATED_SLIPPAGE_BPS = 5.0    
    config.SIMULATED_LATENCY_MAX_MS = 0  # Reduce latency so we don't sleep forever
    config.INITIAL_BALANCE = 1000000.0
    config.RISK_MAX_DRAWDOWN = 0.15         
    config.RISK_MAX_DAILY_LOSS = 0.05
    config.MAX_ORDER_RETRIES = 1
    config.RETRY_BACKOFF_FACTOR = 0.01
    
    print("Mocking Exchange...")
    exchange = MagicMock()
    exchange.fetch_balance = AsyncMock(return_value={'total': {'USDT': 1000000.0}, 'free': {'USDT': 1000000.0}, 'used': {'USDT': 0.0}})
    exchange.init = AsyncMock()
    exchange.fetch_open_orders = AsyncMock(return_value=[])
    exchange.get_market_precision = MagicMock(return_value=(2, 4))
    exchange.cancel_all_orders = AsyncMock()
    exchange.is_connected = True
    exchange.network_latency = 0.0

    print("Creating BotRunner...")
    logging.getLogger('root').setLevel(logging.CRITICAL) 
    logging.getLogger('risk.risk_manager').setLevel(logging.CRITICAL)
    bot = BotRunner(config=config, exchange=exchange)
    
    bot.telegram = MagicMock()
    bot.telegram.is_healthy.return_value = True
    bot.telegram.info = AsyncMock()
    bot.telegram.trade = AsyncMock()
    bot.telegram.error = AsyncMock()
    bot.telegram.warning = AsyncMock()
    bot.telegram.critical = AsyncMock()
    
    if hasattr(bot, 'paper_manager'):
        bot.paper_manager.internal_usd_balance = 1000000.0
        
    print("Loading 30-Day Stream...")
    historical_feed = create_thirty_day_feed()
    feed_length = len(historical_feed)
    
    print("\n=======================================================")
    print("          END-TO-END 30-DAY SYSTEM SIMULATION")
    print("=======================================================")
    
    errors = []
    
    import time
    
    print("Starting chronological execution loop...")
    try:
        # Loop over historical arrays natively
        for i in range(50, feed_length, 2):
            t0 = time.time()
            print(f"[*] {i} START")
            if i % 10 == 0:
                print(f"[*] Processing Candle Iteration {i}/{feed_length}")
            current_slice = historical_feed.iloc[:i]
            bot.data_engine.data[("BTC/USDT", "1h")] = current_slice
            
            await bot.iterate("BTC/USDT")
            
            t1 = time.time()
            print(f"[*] {i} DONE in {t1-t0:.2f}s")
                
            if hasattr(bot.execution_router, 'risk_engine') and bot.execution_router.risk_engine.should_shutdown():
                errors.append("System Shut Down Due to Drawdown Limit! (Expected safety trigger if severe loss)")
                break
    except Exception as e:
        print(f"SIMULATION CRASHED mid-stream! Unexpected traceback: {e}")
        return

    print("\nExtracting metrics...")
    trades_taken = 0
    if hasattr(bot, 'execution_router') and hasattr(bot.execution_router, 'paper_manager'):
        trades_taken = len(bot.execution_router.paper_manager.state.get("history", []))
        if trades_taken == 0:
            trades_taken = len(bot.execution_router.paper_manager.state.get("positions", {}).keys())
     # 5. Extract results
    if hasattr(bot, 'execution_router') and hasattr(bot.execution_router, 'paper_manager'):
        final_equity = bot.execution_router.paper_manager.get_equity({})
    else:
        final_equity = 1000000.0
        
    pnl = final_equity - 1000000.0
    pnl_pct = (pnl / 1000000.0) * 100
    
    print("\n================ FINAL REPORT =========================")
    print(f"[*] Final Equity:    ${final_equity:,.2f}")
    print(f"[*] Total Net PnL:   ${pnl:,.2f}")
    print(f"[*] Trades Executed: {trades_taken}")
    print(f"[*] System Health:   CRASH-FREE")
    if errors:
        print(f"[*] Risk Failsafes:  {errors[0]}")
    print("=======================================================\n")

if __name__ == "__main__":
    asyncio.run(main())
