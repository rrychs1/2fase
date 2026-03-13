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
    
    def _get_conn(self):
        """Helper to get a connection and ensure it is closed later if not using context manager properly."""
        return sqlite3.connect(self.db_path)

    def save_trade(self, trade_data: dict) -> bool:
        """
        Saves a trade to the database.
        Returns True if saved, False if it already exists or failed.
        """
        conn = sqlite3.connect(self.db_path)
        try:
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
        finally:
            conn.close()

    def trade_exists(self, trade_id: str) -> bool:
        """Check if a trade already exists in the database."""
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute('SELECT 1 FROM trades WHERE trade_id = ?', (str(trade_id),))
            return cursor.fetchone() is not None
        except Exception as e:
            logger.error(f"Error checking trade existence: {e}")
            return False
        finally:
            conn.close()
        return False

    def get_recent_trades(self, limit=100) -> list:
        """Fetch the most recent trades."""
        conn = sqlite3.connect(self.db_path)
        try:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM trades ORDER BY closed_at DESC LIMIT ?', (limit,))
            return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Error fetching recent trades: {e}")
            return []
        finally:
            conn.close()
        return []

    def get_stats(self) -> dict:
        """Calculate global trading statistics from the database."""
        conn = sqlite3.connect(self.db_path)
        try:
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
        finally:
            conn.close()
        return {"total_trades": 0, "total_pnl": 0.0, "win_rate": 0.0, "wins": 0}

    # ── Robust methods for dashboard API ─────────────────────

    def get_metrics_snapshot(self) -> dict:
        """
        Return a guaranteed-schema metrics dict for /api/metrics.
        Never raises — returns defaults with has_data=False on any failure.
        """
        default = {
            "has_data": False,
            "balance": 0.0,
            "equity": 0.0,
            "unrealized_pnl": 0.0,
            "total_pnl": 0.0,
            "total_trades": 0,
            "win_rate": 0.0,
        }
        conn = None
        try:
            if not os.path.exists(self.db_path):
                return default

            conn = sqlite3.connect(self.db_path, timeout=5)
            cursor = conn.cursor()

            # ─ Trade stats ───────────────────────────────
            cursor.execute('SELECT COUNT(*) FROM trades')
            row_count = cursor.fetchone()
            total_trades = row_count[0] if row_count else 0

            cursor.execute('SELECT COALESCE(SUM(realized_pnl), 0.0) FROM trades')
            row_pnl = cursor.fetchone()
            total_pnl = float(row_pnl[0]) if row_pnl else 0.0

            cursor.execute('SELECT COUNT(*) FROM trades WHERE realized_pnl > 0')
            row_wins = cursor.fetchone()
            wins = row_wins[0] if row_wins else 0
            win_rate = round((float(wins) / total_trades * 100), 1) if total_trades > 0 else 0.0

            # ─ Balance/Equity (from account_snapshots if it exists) ──
            balance, equity = 0.0, 0.0
            try:
                row = cursor.execute(
                    "SELECT balance, equity FROM account_snapshots ORDER BY ts DESC LIMIT 1"
                ).fetchone()
                if row:
                    balance = float(row[0] or 0)
                    equity = float(row[1] or 0)
            except sqlite3.OperationalError:
                # Table doesn't exist — that's fine
                pass

            has_data = total_trades > 0 or balance > 0

            return {
                "has_data": has_data,
                "balance": round(balance, 2),
                "equity": round(equity, 2),
                "unrealized_pnl": round(equity - balance, 2),
                "total_pnl": round(total_pnl, 2),
                "total_trades": total_trades,
                "win_rate": win_rate,
            }
        except Exception as e:
            logger.error(f"get_metrics_snapshot failed: {e}")
            return default
        finally:
            if conn: conn.close()
        return default

    def get_recent_trades_list(self, limit: int = 50) -> list:
        """
        Return recent trades as a list of dicts with normalized field names.
        Never raises — returns [] on failure.
        """
        conn = sqlite3.connect(self.db_path, timeout=5)
        try:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(
                'SELECT trade_id, symbol, side, price, amount, '
                'realized_pnl, closed_at FROM trades '
                'ORDER BY closed_at DESC LIMIT ?',
                (limit,)
            )
            result = []
            for row in cursor.fetchall():
                result.append({
                    "id": row["trade_id"],
                    "symbol": row["symbol"],
                    "side": row["side"],
                    "price": float(row["price"] or 0),
                    "amount": float(row["amount"] or 0),
                    "pnl": float(row["realized_pnl"] or 0),
                    "closed_at": row["closed_at"] or "",
                })
            return result
        except Exception as e:
            logger.error(f"get_recent_trades_list failed: {e}")
            return []
        finally:
            conn.close()
        return []

