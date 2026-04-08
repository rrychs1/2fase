import asyncio
import os
import json
import ccxt.async_support as ccxt
from dotenv import load_dotenv
from exchange.exchange_client import ExchangeClient
from config.config_loader import Config

# Force Testnet
os.environ["USE_TESTNET"] = "True"
Config.USE_TESTNET = True


async def manage_account():
    print("--- Binance Account Manager ---")
    client = ExchangeClient()
    await client.init()

    print("\n1. Fetching Balance...")
    balance = await client.fetch_balance()
    usdt = balance.get("total", {}).get("USDT", 0.0)
    print(f"   USDT Balance: {usdt:.2f}")

    print("\n2. Fetching Positions...")
    positions = await client.fetch_positions()
    print(f"   Open Positions: {len(positions)}")
    for p in positions:
        print(
            f"   - {p['symbol']}: {p['contracts']} contracts | PnL: {p['unrealizedPnl']}"
        )

    print("\n3. Fetching Open Orders...")
    total_orders = 0
    for symbol in Config.SYMBOLS:
        orders = await client.fetch_open_orders(symbol)
        total_orders += len(orders)
        if orders:
            print(f"   {symbol}: {len(orders)} orders")
            for o in orders[:5]:
                print(
                    f"     [{o['id']}] {o['side']} {o['type']} {o['amount']} @ {o['price']}"
                )

    if total_orders == 0:
        print("   No open orders found.")

    # --- CLEANUP LOGIC ---
    print("\n--- Cleanup Actions ---")
    # Cancel all orders
    if total_orders > 0:
        print("Cancelling ALL open orders...")
        for symbol in Config.SYMBOLS:
            await client.cancel_all_orders(symbol)
        print("Orders cancelled.")

    # Close positions
    if positions:
        print("Closing ALL positions...")
        for p in positions:
            symbol = p["symbol"]
            amt = abs(float(p["contracts"]))
            side = "sell" if float(p["contracts"]) > 0 else "buy"
            print(f"Closing {symbol} ({side} {amt})...")
            # Market Reduce-Only
            await client.create_order(
                symbol, "market", side, amt, params={"reduceOnly": True}
            )
        print("Positions closed.")

    print("\n--- Final State ---")
    balance = await client.fetch_balance()
    print(f"Final USDT: {balance.get('total', {}).get('USDT', 0.0):.2f}")

    await client.close()


if __name__ == "__main__":
    asyncio.run(manage_account())
