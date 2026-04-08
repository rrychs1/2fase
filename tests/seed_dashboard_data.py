"""
Seed script — generates test data for local dashboard testing.

Usage:
    python tests/seed_dashboard_data.py

Creates:
    data/trading_v3.db     — SQLite with 10 sample trades
    data/dashboard_state.json — Fresh bot state with positions & regimes
    data/papers.jsonl      — 50 equity curve data points
    data/alerts.jsonl      — 5 sample notifications
    status.json            — Legacy status file
"""

import json
import os
import sqlite3
import sys
import random
from datetime import datetime, timedelta

# Project root
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

DATA = os.path.join(ROOT, "data")
os.makedirs(DATA, exist_ok=True)
os.makedirs(os.path.join(ROOT, "logs"), exist_ok=True)


def seed_db():
    """Create trading_v3.db with 10 sample trades."""
    db_path = os.path.join(DATA, "trading_v3.db")
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    cur.execute("DROP TABLE IF EXISTS trades")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS trades (
            trade_id TEXT PRIMARY KEY,
            symbol TEXT NOT NULL,
            side TEXT NOT NULL,
            price REAL NOT NULL,
            amount REAL NOT NULL,
            realized_pnl REAL DEFAULT 0,
            closed_at TEXT NOT NULL,
            is_suspicious INTEGER DEFAULT 0,
            raw_data TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_trades_symbol ON trades(symbol)")

    now = datetime.now()
    trades = []
    symbols = ["BTC/USDT", "ETH/USDT"]
    for i in range(10):
        t = now - timedelta(hours=10 - i, minutes=random.randint(0, 59))
        sym = symbols[i % 2]
        side = random.choice(["buy", "sell"])
        price = (
            95000 + random.uniform(-2000, 2000)
            if "BTC" in sym
            else 3400 + random.uniform(-200, 200)
        )
        pnl = round(random.uniform(-15, 25), 2)
        trades.append(
            (
                f"test-trade-{i:04d}",
                sym,
                side,
                round(price, 2),
                round(random.uniform(0.001, 0.05), 4),
                pnl,
                t.isoformat(),
                0,
                "{}",
            )
        )

    cur.executemany(
        "INSERT INTO trades VALUES (?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)", trades
    )
    conn.commit()
    conn.close()
    print(f"  [+] Created {db_path} with {len(trades)} trades")


def seed_dashboard_state():
    """Create a fresh dashboard_state.json."""
    from state.state_manager import write_bot_state

    state = {
        "running": True,
        "balance": 4030.31,
        "equity": 4035.12,
        "unrealized_pnl": 4.81,
        "mode": "Paper",
        "positions": {
            "BTC/USDT": {
                "side": "LONG",
                "amount": 0.002,
                "average_price": 94850.00,
                "stop_loss": 94200.00,
                "take_profit": 96500.00,
            }
        },
        "pending_orders": [
            {"symbol": "ETH/USDT", "side": "LONG", "price": 3350.00, "type": "grid"},
            {"symbol": "ETH/USDT", "side": "SHORT", "price": 3550.00, "type": "grid"},
        ],
        "history": [
            {
                "symbol": "BTC/USDT",
                "side": "LONG",
                "pnl": 12.50,
                "closed_at": (datetime.now() - timedelta(hours=2)).isoformat(),
            },
            {
                "symbol": "ETH/USDT",
                "side": "SHORT",
                "pnl": -3.20,
                "closed_at": (datetime.now() - timedelta(hours=1)).isoformat(),
            },
            {
                "symbol": "BTC/USDT",
                "side": "SHORT",
                "pnl": 8.75,
                "closed_at": datetime.now().isoformat(),
            },
        ],
        "global_stats": {
            "total_trades": 10,
            "total_pnl": 42.35,
            "win_rate": 60.0,
            "wins": 6,
        },
        "regimes": {"BTC/USDT": "trend", "ETH/USDT": "range"},
        "prices": {"BTC/USDT": 95120.50, "ETH/USDT": 3425.80},
        "iteration": 47,
        "uptime": "1:23:45",
        "metrics": {
            "signals_processed": 94,
            "orders_placed": 12,
            "orders_failed": 1,
            "errors": 0,
        },
        "status": {
            "trading_enabled": True,
            "paper_trading_enabled": True,
            "exchange_connected": True,
            "last_change_reason": "System started in Paper mode",
        },
        "exchange_status": "Connected",
        "last_error": None,
        "telegram_healthy": True,
    }

    state_path = os.path.join(DATA, "dashboard_state.json")
    write_bot_state(state_path, state)
    print(f"  [+] Created {state_path}")

    # Also write legacy status.json
    legacy = {
        "running": True,
        "status": "Analyzing markets",
        "uptime": "1:23:45",
        "mode": "Paper",
        "last_loop": datetime.now().isoformat(),
    }
    write_bot_state(os.path.join(ROOT, "status.json"), legacy)
    print(f"  [+] Created status.json")


def seed_papers_jsonl():
    """Create 50 equity curve points."""
    path = os.path.join(DATA, "papers.jsonl")
    now = datetime.now()
    equity = 4000.0

    with open(path, "w", encoding="utf-8") as f:
        for i in range(50):
            ts = now - timedelta(minutes=(50 - i) * 5)
            delta = random.uniform(-8, 12)
            equity += delta
            record = {
                "ts": ts.isoformat(),
                "virtual_equity": round(equity, 2),
                "price": round(95000 + random.uniform(-1000, 1000), 2),
                "regime": random.choice(["trend", "range"]),
                "symbol": "BTC/USDT",
                "signals_count": random.randint(0, 5),
            }
            f.write(json.dumps(record) + "\n")

    print(f"  [+] Created {path} with 50 data points")


def seed_alerts():
    """Create 5 sample alert entries."""
    path = os.path.join(DATA, "alerts.jsonl")
    now = datetime.now()
    alerts = [
        {
            "ts": (now - timedelta(minutes=30)).isoformat(),
            "level": "INFO",
            "msg": "Bot started in Paper mode",
        },
        {
            "ts": (now - timedelta(minutes=20)).isoformat(),
            "level": "TRADE",
            "msg": "BTC/USDT LONG opened @ 94850.00",
        },
        {
            "ts": (now - timedelta(minutes=15)).isoformat(),
            "level": "WARNING",
            "msg": "High volatility detected on ETH/USDT",
        },
        {
            "ts": (now - timedelta(minutes=5)).isoformat(),
            "level": "TRADE",
            "msg": "BTC/USDT LONG closed PnL: +12.50",
        },
        {"ts": now.isoformat(), "level": "INFO", "msg": "Iteration 47 completed"},
    ]
    with open(path, "w", encoding="utf-8") as f:
        for a in alerts:
            f.write(json.dumps(a) + "\n")

    print(f"  [+] Created {path} with {len(alerts)} alerts")


def seed_log_file():
    """Create a minimal bot.log."""
    path = os.path.join(ROOT, "logs", "bot.log")
    now = datetime.now()
    lines = [
        f"{now - timedelta(minutes=30)} INFO     Bot started in Paper mode",
        f"{now - timedelta(minutes=29)} INFO     Exchange connection verified. Equity: 4030.31 USDT",
        f"{now - timedelta(minutes=28)} INFO     Symbols: BTC/USDT, ETH/USDT",
        f"{now - timedelta(minutes=20)} INFO     [Iter 10] BTC/USDT: regime=trend, price=94850.00",
        f"{now - timedelta(minutes=15)} WARNING  High volatility on ETH/USDT (ATR > 2x normal)",
        f"{now - timedelta(minutes=10)} INFO     [Iter 30] Placed grid order ETH/USDT LONG @ 3350.00",
        f"{now - timedelta(minutes=5)}  INFO     [Iter 45] BTC/USDT LONG closed PnL: +12.50",
        f"{now} INFO     [Iter 47] Cycle complete. Equity: 4035.12 USDT",
    ]
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    print(f"  [+] Created {path}")


if __name__ == "__main__":
    print("\n=== Seeding Dashboard Test Data ===\n")
    seed_db()
    seed_dashboard_state()
    seed_papers_jsonl()
    seed_alerts()
    seed_log_file()
    print("\n=== Done! Now run: python run_dashboard.py ===\n")
