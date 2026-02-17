import ccxt.async_support as ccxt
import asyncio

async def test_auth():
    print("Testing Binance Futures Testnet Auth (Async)...")
    config = {
        'apiKey': 'QjXWYvcjCMGKfgrgEicpBEsL1TQpIznGFqWhbgav5PbcNSQMjhzbC6LEnMWg1EU4',
        'secret': 'aZXDZ0COMbjG0gRjwZuaBSNXmeBNWw7URFDnNuUtug48yvXXFu3ezwK0tJNRgDwl',
        'enableRateLimit': True,
    }
    
    ex = ccxt.binanceusdm(config)
    ex.set_sandbox_mode(True)
    
    try:
        print("Fetching balance via fapiPrivateV2GetBalance...")
        balance = await ex.fapiPrivateV2GetBalance()
        # balance is usually a list for this specific endpoint on binance
        usdt = next((b for b in balance if b.get('asset') == 'USDT'), None)
        print(f"Success! USDT Balance: {usdt['balance'] if usdt else 'Not found'}")
    except Exception as e:
        print(f"Direct call failed: {e}")
        
    try:
        print("Fetching balance via fetch_balance...")
        bal = await ex.fetch_balance()
        print(f"Success! USDT Total: {bal.get('USDT', {}).get('total', 'Not found')}")
    except Exception as e:
        print(f"fetch_balance failed: {e}")
        
    await ex.close()

if __name__ == "__main__":
    asyncio.run(test_auth())
