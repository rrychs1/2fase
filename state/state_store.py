import sqlite3
import threading
import json
import logging
import os

logger = logging.getLogger(__name__)


class StateStore:
    """
    Robust SQLite-based Persistence Layer guaranteeing atomic writes and crash-recovery.
    Replaces fragile JSON-based states to ensure sync with the exchange.
    """

    def __init__(self, db_path="data/state_shadow.db"):
        self.db_path = db_path
        self._lock = threading.Lock()

        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)

        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""CREATE TABLE IF NOT EXISTS positions (
                                symbol TEXT PRIMARY KEY, 
                                amount REAL, 
                                entry_price REAL)""")
                conn.execute("""CREATE TABLE IF NOT EXISTS balance (
                                id INTEGER PRIMARY KEY, 
                                balance REAL)""")
                conn.execute("""CREATE TABLE IF NOT EXISTS orders (
                                order_id TEXT PRIMARY KEY,
                                status TEXT)""")

    def save_position(self, symbol: str, amount: float, entry_price: float):
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO positions (symbol, amount, entry_price) VALUES (?, ?, ?)",
                    (symbol, amount, entry_price),
                )

    def load_positions(self):
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                c = conn.cursor()
                c.execute("SELECT symbol, amount, entry_price FROM positions")
                return {
                    row[0]: {"amount": row[1], "entry_price": row[2]}
                    for row in c.fetchall()
                }

    def get_position(self, symbol: str):
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                c = conn.cursor()
                c.execute(
                    "SELECT amount, entry_price FROM positions WHERE symbol = ?",
                    (symbol,),
                )
                row = c.fetchone()
                if row:
                    return {"amount": row[0], "entry_price": row[1]}
        return None

    def save_balance(self, balance: float):
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO balance (id, balance) VALUES (1, ?)",
                    (balance,),
                )

    def get_balance(self):
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                c = conn.cursor()
                c.execute("SELECT balance FROM balance WHERE id = 1")
                row = c.fetchone()
                return row[0] if row else 0.0

    def save_order(self, order_id: str, status: str):
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO orders (order_id, status) VALUES (?, ?)",
                    (order_id, status),
                )

    def get_open_orders(self):
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                c = conn.cursor()
                c.execute(
                    "SELECT order_id, status FROM orders WHERE status != 'FILLED' AND status != 'FAILED'"
                )
                return [{"order_id": row[0], "status": row[1]} for row in c.fetchall()]
