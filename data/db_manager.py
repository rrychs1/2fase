import sqlite3
import os
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

class DbManager:
    def __init__(self, db_path="data/trading_v3.db"):
        self.db_path = db_path
        # Ensure directory exists
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._init_db()

    def _init_db(self):
        """Create tables if they don't exist."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                # Trades Table
                cursor.execute('''
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
                ''')
                # Index for faster symbol lookups
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_trades_symbol ON trades(symbol)')
                conn.commit()
                logger.info(f"Database initialized at {self.db_path}")
        except Exception as e:
            logger.error(f"Failed to initialize database: {e}")

    def save_trade(self, trade_data: dict) -> bool:
        """
        Saves a trade to the database.
        Returns True if saved, False if it already exists or failed.
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO trades (
                        trade_id, symbol, side, price, amount, realized_pnl, closed_at, is_suspicious, raw_data
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    str(trade_data.get('id') or trade_data.get('trade_id')),
                    trade_data.get('symbol'),
                    trade_data.get('side'),
                    trade_data.get('price'),
                    trade_data.get('amount'),
                    trade_data.get('pnl', 0.0),
                    trade_data.get('closed_at'),
                    1 if trade_data.get('is_suspicious') else 0,
                    str(trade_data.get('info', {}))
                ))
                conn.commit()
                return True
        except sqlite3.IntegrityError:
            # Duplicate ID - typical for polling
            return False
        except Exception as e:
            logger.error(f"Error saving trade {trade_data.get('id')}: {e}")
            return False

    def trade_exists(self, trade_id: str) -> bool:
        """Check if a trade already exists in the database."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT 1 FROM trades WHERE trade_id = ?', (str(trade_id),))
                return cursor.fetchone() is not None
        except Exception as e:
            logger.error(f"Error checking trade existence: {e}")
            return False

    def get_recent_trades(self, limit=100) -> list:
        """Fetch the most recent trades."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute('SELECT * FROM trades ORDER BY closed_at DESC LIMIT ?', (limit,))
                return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Error fetching recent trades: {e}")
            return []

    def get_stats(self) -> dict:
        """Calculate global trading statistics from the database."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                # Total Trades
                cursor.execute('SELECT COUNT(*) FROM trades')
                total_trades = cursor.fetchone()[0]
                
                # Total PnL
                cursor.execute('SELECT SUM(realized_pnl) FROM trades')
                total_pnl = cursor.fetchone()[0] or 0.0
                
                # Win Rate
                cursor.execute('SELECT COUNT(*) FROM trades WHERE realized_pnl > 0')
                wins = cursor.fetchone()[0]
                win_rate = (wins / total_trades * 100) if total_trades > 0 else 0.0
                
                return {
                    "total_trades": total_trades,
                    "total_pnl": round(float(total_pnl), 2),
                    "win_rate": round(float(win_rate), 1),
                    "wins": wins
                }
        except Exception as e:
            logger.error(f"Error calculating stats: {e}")
            return {"total_trades": 0, "total_pnl": 0.0, "win_rate": 0.0, "wins": 0}
