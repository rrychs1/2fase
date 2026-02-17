
import asyncio
import os
import time
import ccxt.async_support as ccxt
from datetime import datetime
from dotenv import load_dotenv
import traceback

load_dotenv()

def log(msg):
    print(msg)
    with open("debug_result.txt", "a", encoding="utf-8") as f:
        f.write(str(msg) + "\n")

async def debug_auth():
    # Clear previous log
    with open("debug_result.txt", "w", encoding="utf-8") as f:
        f.write("--- Debug Log Start ---\n")

    log(f"--- Debug Auth v3 ---")
    log(f"CCXT Version: {ccxt.__version__}")
    log(f"System Time: {datetime.now()}")
    
    api_key = os.getenv('BINANCE_API_KEY')
    secret_key = os.getenv('BINANCE_SECRET_KEY')
    use_testnet = os.getenv('USE_TESTNET')

    log(f"USE_TESTNET: {use_testnet}")
    log(f"API Key: {api_key[:5]}... (Length: {len(api_key)})")

    # --- RAW NETWORK CHECK ---
    import requests
    try:
        url = "https://testnet.binancefuture.com/fapi/v1/time"
        log(f"Testing raw connectivity to {url}...")
        r = requests.get(url, timeout=5)
        log(f"[NETWORK] Status: {r.status_code}, Latency: {r.elapsed.total_seconds()}s")
        log(f"[NETWORK] Body: {r.text[:100]}")
    except Exception as e:
        log(f"[NETWORK ERROR] Could not reach Testnet: {e}")
    # -------------------------
    
    config = {
        'apiKey': api_key,
        'secret': secret_key,
        'enableRateLimit': True,
        'options': {'defaultType': 'future'} 
    }
    
    exchange = ccxt.binance(config) # Use generic binance with option
    
    try:
        if str(use_testnet).lower() == 'true':
            log("[CONFIG] Enabling Testnet/Sandbox Mode")
            exchange.set_sandbox_mode(True)
            # Force URLs exactly as bot does
            testnet_fapi = 'https://testnet.binancefuture.com/fapi/v1'
            exchange.urls['api']['public'] = testnet_fapi
            exchange.urls['api']['private'] = testnet_fapi
            exchange.urls['api']['fapiPublic'] = testnet_fapi
            exchange.urls['api']['fapiPrivate'] = testnet_fapi
            log(f"[CONFIG] Overridden URLs to: {testnet_fapi}")
        
        log(f"[INFO] Fetching public time...")
        server_time = await exchange.fetch_time()
        log(f"[SUCCESS] Server Time: {datetime.fromtimestamp(server_time/1000)}")
        
        diff = abs(time.time() * 1000 - server_time)
        log(f"[INFO] Time Difference: {diff}ms")

        log(f"[INFO] Fetching balance...")
        balance = await exchange.fetch_balance()
        log(f"[SUCCESS] Balance Fetch OK. Total USDT: {balance.get('total', {}).get('USDT', 'N/A')}")
        
    except Exception as e:
        log(f"\n[CRITICAL ERROR] {type(e).__name__}: {str(e)}")
        # log(traceback.format_exc())
    finally:
        await exchange.close()

if __name__ == "__main__":
    asyncio.run(debug_auth())
