import json
import os
from datetime import datetime

def ping():
    if not os.path.exists("status.json"):
        print("Bot status file not found. Is the bot running?")
        return

    try:
        with open("status.json", "r") as f:
            status = json.load(f)
        
        print("-" * 30)
        print("   BINANCE BOT PING")
        print("-" * 30)
        print(f"Status:    {status.get('status')}")
        print(f"Uptime:    {status.get('uptime')}")
        print(f"Mode:      {status.get('mode')}")
        print(f"Symbols:   {', '.join(status.get('connected_symbols', []))}")
        print(f"Last Loop: {status.get('last_loop_timestamp')}")
        print("-" * 30)
        
    except Exception as e:
        print(f"Error reading status: {e}")

if __name__ == "__main__":
    ping()
