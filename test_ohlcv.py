import ccxt.async_support as ccxt
import asyncio


async def test():
    print("Testing CCXT Binance Futures Public OHLCV with longer timeout...")

    ex = ccxt.binanceusdm(
        {
            "enableRateLimit": True,
            "timeout": 30000,
        }
    )

    # Try fetching without load_markets
    print("Attempting fetch_ohlcv directly...")
    try:
        ohlcv = await ex.fetch_ohlcv("BTC/USDT", "1m", limit=5)
        print(f"Success! {len(ohlcv)} candles.")
    except Exception as e:
        print(f"Direct fetch failed: {e}")

    await ex.close()


if __name__ == "__main__":
    asyncio.run(test())
