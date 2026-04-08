"""
Trading Bot Dashboard — Flask backend.
Reads unified dashboard_state.json + papers.jsonl + logs.
"""

import json
import os
import sqlite3
from flask import Flask, render_template, jsonify
from collections import deque

import datetime
from dotenv import load_dotenv
from state.state_manager import load_bot_state, is_state_fresh

# Absolute project root
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Load env variables early
load_dotenv(os.path.join(BASE_DIR, ".env"))

# Load paths from env or defaults
STATE_FILE = os.getenv("STATE_FILE", "data/dashboard_state.json")
DB_PATH = os.getenv("DB_PATH", "data/trading_v3.db")
LOG_FILE = os.getenv("LOG_FILE", "logs/bot.log")
PAPERS_FILE = os.getenv("PAPERS_FILE", "papers.jsonl")


def _get_abs_path(filename):
    if os.path.isabs(filename):
        return filename
    return os.path.join(BASE_DIR, filename)


app = Flask(__name__)


def _read_json(filename):
    path = _get_abs_path(filename)
    try:
        if not os.path.exists(path):
            return {}
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
            if not content.strip():
                return {}
            # Senior Hardening: Robust JSON loading
            try:
                return json.loads(content)
            except json.JSONDecodeError as je:
                print(f"[DASHBOARD] Corrupt JSON in {filename}: {je}")
                return {}
    except Exception as e:
        print(f"[DASHBOARD] Error reading JSON {filename}: {e}")
        return {}


def _read_jsonl(filename, max_lines=500):
    path = _get_abs_path(filename)
    if not os.path.exists(path):
        return []
    data = deque(maxlen=max_lines)
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        data.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
    except Exception:
        pass
    return list(data)


def _state_is_fresh(filename, max_age_s=120):
    """Return True if the state file exists and was written within max_age_s seconds."""
    return is_state_fresh(_get_abs_path(filename), max_age_seconds=max_age_s)


def _read_db_account():
    """Fallback: read balance/equity/trades directly from trading_v3.db."""
    db_path = _get_abs_path(DB_PATH)
    if not os.path.exists(db_path):
        return {}
    try:
        conn = sqlite3.connect(db_path, timeout=5)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        # Latest balance snapshot (table may not exist yet)
        balance, equity = 0.0, 0.0
        try:
            row = cur.execute(
                "SELECT balance, equity FROM account_snapshots ORDER BY ts DESC LIMIT 1"
            ).fetchone()
            if row:
                balance = float(row["balance"] or 0)
                equity = float(row["equity"] or 0)
        except Exception:
            pass

        # Recent trades
        history = []
        total_pnl = 0.0
        wins = 0
        try:
            rows = cur.execute(
                "SELECT * FROM trades ORDER BY closed_at DESC LIMIT 100"
            ).fetchall()
            for r in rows:
                t = dict(r)
                pnl = float(t.get("realized_pnl") or t.get("pnl") or 0)
                t["pnl"] = pnl
                total_pnl += pnl
                if pnl > 0:
                    wins += 1
                history.append(t)
        except Exception:
            pass

        conn.close()

        total = len(history)
        win_rate = round(wins / total * 100, 1) if total > 0 else 0.0
        return {
            "balance": round(balance, 2),
            "equity": round(equity or balance, 2),
            "unrealized_pnl": round((equity or balance) - balance, 2),
            "positions": {},
            "pending_orders": [],
            "history": history[:50],
            "total_trades": total,
            "win_rate": win_rate,
            "total_pnl": round(total_pnl, 2),
            "regimes": {},
            "prices": {},
            "mode": "Live",
        }
    except Exception as e:
        print(f"[DASHBOARD] DB fallback error: {e}")
        return {}


def _read_log_tail(filename=None, n=80):
    if filename is None:
        filename = LOG_FILE
    path = _get_abs_path(filename)
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            lines = deque(f, maxlen=n)
        return [l.rstrip() for l in lines]
    except Exception:
        return []


# ── Lazy DB singleton (only created when first needed) ────────
_db = None


def _get_db():
    global _db
    if _db is None:
        from data.db_manager import DbManager

        _db = DbManager(_get_abs_path(DB_PATH))
    return _db


# ── Internal helpers for robust data assembly ─────────────────


def _bot_state_snapshot() -> dict:
    """
    Read the bot state file using state_manager.
    Returns {} if the file is missing or unreadable — never raises.
    """
    state = load_bot_state(_get_abs_path(STATE_FILE))
    return state if state is not None else {}


def _is_bot_active(state: dict) -> bool:
    """Check if the bot wrote its state within the last 120 seconds."""
    ts_str = state.get("timestamp", "")
    if not ts_str:
        return False
    try:
        last_dt = datetime.datetime.fromisoformat(ts_str)
        return (datetime.datetime.now() - last_dt).total_seconds() < 120
    except Exception:
        return False


def _compute_metrics(state: dict) -> dict:
    """
    Build a guaranteed /api/metrics response by merging:
      1. dashboard_state.json (primary — written every bot cycle)
      2. DB stats (fallback)
      3. In-memory paper history (fallback for ANALYSIS_ONLY mode)
    Never raises.
    """
    # Start from DB as a safe base
    db = _get_db()
    db_metrics = db.get_metrics_snapshot()

    # If the state file has richer data, prefer it
    if state:
        balance = _safe_float(state.get("balance"), db_metrics["balance"])
        equity = _safe_float(state.get("equity"), balance)
        unrealized_pnl = _safe_float(state.get("unrealized_pnl"), equity - balance)

        # Stats: prefer global_stats from state (bot writes them from DB each cycle)
        # then fall back to paper history, then DB
        global_stats = state.get("global_stats", {})
        history = state.get("history", [])

        if global_stats and global_stats.get("total_trades", 0) > 0:
            total_trades = global_stats["total_trades"]
            total_pnl = _safe_float(global_stats.get("total_pnl"), 0)
            win_rate = _safe_float(global_stats.get("win_rate"), 0)
        elif history:
            # Paper mode: compute from in-memory history
            total_trades = len(history)
            total_pnl = sum(_safe_float(t.get("pnl"), 0) for t in history)
            wins = sum(1 for t in history if _safe_float(t.get("pnl"), 0) > 0)
            win_rate = (
                round((wins / total_trades * 100), 1) if total_trades > 0 else 0.0
            )
        else:
            total_trades = db_metrics["total_trades"]
            total_pnl = db_metrics["total_pnl"]
            win_rate = db_metrics["win_rate"]

        has_data = balance > 0 or total_trades > 0 or equity > 0
    else:
        # No state file at all — pure DB fallback
        balance = db_metrics["balance"]
        equity = db_metrics["equity"]
        unrealized_pnl = db_metrics["unrealized_pnl"]
        total_pnl = db_metrics["total_pnl"]
        total_trades = db_metrics["total_trades"]
        win_rate = db_metrics["win_rate"]
        has_data = db_metrics["has_data"]

    return {
        "has_data": has_data,
        "balance": round(balance, 2),
        "equity": round(equity, 2),
        "unrealized_pnl": round(unrealized_pnl, 2),
        "total_pnl": round(total_pnl, 2),
        "total_trades": total_trades,
        "win_rate": round(win_rate, 1),
    }


def _safe_float(val, default=0.0) -> float:
    """Coerce any value to float, returning default on failure."""
    if val is None:
        return float(default)
    try:
        return float(val)
    except (TypeError, ValueError):
        return float(default)


# ─────────────────────────────────────────── routes ──────────
@app.route("/")
def index():
    return render_template("index.html")


# ═══════════════════════════════════════════════════════════════
#  /api/state — Instantaneous bot runtime snapshot
# ═══════════════════════════════════════════════════════════════
@app.route("/api/state")
def api_state():
    """
    Guaranteed schema:
    {
        "running": bool,
        "mode": str,
        "iteration": int,
        "last_loop_ts": str | null,
        "uptime": str,
        "equity": float,
        "open_positions": [...],
        "pending_orders": [...],
        "regimes": {...},
        "prices": {...},
        "last_error": {...} | null,
        "exchange_status": str,
        "telegram_healthy": bool,
        "bot_status": {...},
        "has_data": bool
    }
    """
    try:
        state = _bot_state_snapshot()
        is_active = _is_bot_active(state)

        # Normalize positions to a list (state stores them as dict keyed by symbol)
        raw_positions = state.get("positions", {})
        if isinstance(raw_positions, dict):
            positions_list = []
            for symbol, pos in raw_positions.items():
                if isinstance(pos, dict) and pos:
                    pos_entry = {"symbol": symbol}
                    pos_entry.update(pos)
                    positions_list.append(pos_entry)
            open_positions = positions_list
        elif isinstance(raw_positions, list):
            open_positions = raw_positions
        else:
            open_positions = []

        # Trade history: prefer state file, fall back to DB
        history = state.get("history", [])
        if not history:
            db = _get_db()
            history = db.get_recent_trades_list(limit=50)

        return jsonify(
            {
                "running": is_active,
                "mode": state.get("mode", "Unknown"),
                "iteration": state.get("iteration", 0),
                "last_loop_ts": state.get("timestamp"),
                "uptime": state.get("uptime", "--"),
                "equity": _safe_float(state.get("equity")),
                "open_positions": open_positions,
                "pending_orders": state.get("pending_orders", []),
                "history": history[:50],
                "regimes": state.get("regimes", {}),
                "prices": state.get("prices", {}),
                "last_error": state.get("last_error"),
                "exchange_status": state.get("exchange_status", "Unknown"),
                "telegram_healthy": state.get("telegram_healthy", True),
                "bot_status": state.get("status", {}),
                "has_data": bool(state),
            }
        )
    except Exception as e:
        # Absolute last resort — still return valid JSON, never a 500
        return jsonify(
            {
                "running": False,
                "mode": "Unknown",
                "iteration": 0,
                "last_loop_ts": None,
                "uptime": "--",
                "equity": 0.0,
                "open_positions": [],
                "pending_orders": [],
                "history": [],
                "regimes": {},
                "prices": {},
                "last_error": {
                    "type": "DashboardError",
                    "msg": str(e),
                    "ts": datetime.datetime.now().isoformat(),
                },
                "exchange_status": "Unknown",
                "telegram_healthy": False,
                "bot_status": {},
                "has_data": False,
            }
        )


# ═══════════════════════════════════════════════════════════════
#  /api/metrics — Aggregated trading KPIs
# ═══════════════════════════════════════════════════════════════
@app.route("/api/metrics")
def api_metrics():
    """
    Guaranteed schema:
    {
        "has_data": bool,
        "balance": float,
        "equity": float,
        "unrealized_pnl": float,
        "total_pnl": float,
        "total_trades": int,
        "win_rate": float
    }
    """
    try:
        state = _bot_state_snapshot()
        return jsonify(_compute_metrics(state))
    except Exception as e:
        return jsonify(
            {
                "has_data": False,
                "balance": 0.0,
                "equity": 0.0,
                "unrealized_pnl": 0.0,
                "total_pnl": 0.0,
                "total_trades": 0,
                "win_rate": 0.0,
                "_error": str(e),
            }
        )


# ═══════════════════════════════════════════════════════════════
#  Legacy endpoints (preserved for backward compatibility)
# ═══════════════════════════════════════════════════════════════


@app.route("/api/status")
def api_status():
    """Legacy — delegates to /api/state logic with old field names."""
    state = _bot_state_snapshot()
    is_active = _is_bot_active(state)

    if state:
        return jsonify(
            {
                "status": "Running" if is_active else "Offline",
                "is_active": is_active,
                "uptime": state.get("uptime", "--"),
                "mode": state.get("mode", "Unknown"),
                "last_loop": state.get("timestamp", ""),
                "iteration": state.get("iteration", 0),
                "last_error": state.get("last_error"),
                "telegram_healthy": state.get("telegram_healthy", True),
                "exchange_status": state.get("exchange_status", "Unknown"),
                "bot_status": state.get("status", {}),
            }
        )

    status_fallback = _read_json("status.json")
    if status_fallback:
        status_fallback["is_active"] = False
        return jsonify(status_fallback)

    return jsonify({"status": "Offline", "is_active": False})


@app.route("/api/account")
def api_account():
    """Legacy — merges /api/state + /api/metrics in old format."""
    state = _bot_state_snapshot()
    metrics = _compute_metrics(state)
    history = state.get("history", []) if state else []

    if not history:
        # Try DB fallback
        db = _get_db()
        history = db.get_recent_trades_list(limit=50)

    return jsonify(
        {
            "balance": metrics["balance"],
            "equity": metrics["equity"],
            "unrealized_pnl": metrics["unrealized_pnl"],
            "positions": state.get("positions", {}) if state else {},
            "pending_orders": state.get("pending_orders", []) if state else [],
            "history": history[:50],
            "total_trades": metrics["total_trades"],
            "win_rate": metrics["win_rate"],
            "total_pnl": metrics["total_pnl"],
            "regimes": state.get("regimes", {}) if state else {},
            "prices": state.get("prices", {}) if state else {},
            "mode": state.get("mode", "Unknown") if state else "Unknown",
            "has_data": metrics["has_data"],
        }
    )


@app.route("/api/equity-history")
def api_equity_history():
    records = _read_jsonl(PAPERS_FILE, max_lines=1000)
    points = []
    for r in records:
        points.append(
            {
                "ts": r.get("ts", ""),
                "equity": r.get("virtual_equity", 10000),
                "price": r.get("price", 0),
                "regime": r.get("regime", ""),
                "symbol": r.get("symbol", ""),
                "signals": r.get("signals_count", 0),
            }
        )
    return jsonify(points)


@app.route("/api/logs")
def api_logs():
    try:
        lines = _read_log_tail()
        return jsonify(lines)
    except Exception:
        return jsonify([])


@app.route("/api/alerts")
def api_alerts():
    """Recent Telegram alerts persistent on disk."""
    try:
        alerts = _read_jsonl("data/alerts.jsonl", max_lines=50)
        alerts.reverse()
        return jsonify(alerts)
    except Exception:
        return jsonify([])


@app.route("/dashboard/health")
def healthcheck():
    """Healthcheck endpoint for Docker/DigitalOcean."""
    try:
        db_path = _get_abs_path(DB_PATH)
        db_ok = os.path.exists(db_path)
        state_fresh = _state_is_fresh(STATE_FILE)

        # Also check if DB actually has data (not just exists)
        db_has_data = False
        if db_ok:
            try:
                db = _get_db()
                db_has_data = db.get_metrics_snapshot().get("has_data", False)
            except Exception:
                pass

        return (
            jsonify(
                {
                    "status": "healthy",
                    "timestamp": datetime.datetime.now().isoformat(),
                    "can_read_bot_state": state_fresh,
                    "state_file": _get_abs_path(STATE_FILE),
                    "database_ok": db_ok,
                    "database_has_data": db_has_data,
                    "system": "resilient",
                }
            ),
            200,
        )
    except Exception as e:
        return jsonify({"status": "degraded", "error": str(e)}), 200


@app.route("/health")
def health_endpoint():
    """
    System health endpoint -- returns live health data from the HealthMonitor.

    Reads health_state.json written by the bot's HealthMonitor,
    merges with dashboard-local checks (DB, state freshness).
    """
    try:
        import psutil

        # Dashboard-local health info
        process = psutil.Process(os.getpid())
        dashboard_mem = round(process.memory_info().rss / (1024 * 1024), 1)

        # Bot health report (written by HealthMonitor via state_manager)
        health_path = _get_abs_path("data/health_state.json")
        bot_health = {}
        if os.path.exists(health_path):
            try:
                with open(health_path, "r", encoding="utf-8") as f:
                    bot_health = json.loads(f.read())
            except Exception:
                pass

        state_fresh = _state_is_fresh(STATE_FILE)

        response = {
            "status": bot_health.get("status", "unknown"),
            "timestamp": datetime.datetime.now().isoformat(),
            "bot": bot_health if bot_health else {"status": "offline"},
            "dashboard": {
                "memory_mb": dashboard_mem,
                "bot_state_fresh": state_fresh,
            },
        }

        status_code = 200 if bot_health.get("status") != "degraded" else 503
        return jsonify(response), status_code

    except Exception as e:
        return (
            jsonify(
                {
                    "status": "error",
                    "error": str(e),
                    "timestamp": datetime.datetime.now().isoformat(),
                }
            ),
            500,
        )


if __name__ == "__main__":
    import socket

    port = int(os.getenv("DASHBOARD_PORT", 8000))
    host = os.getenv("DASHBOARD_HOST", "0.0.0.0")

    # Check if port is in use and auto-select if needed
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1)
        try:
            s.bind((host, port))
        except OSError:
            print(f"[DASHBOARD] Port {port} in use, scanning for a free port...")
            for offset in range(1, 20):
                candidate = port + offset
                try:
                    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s2:
                        s2.settimeout(1)
                        s2.bind((host, candidate))
                    port = candidate
                    break
                except OSError:
                    continue
            else:
                print("[DASHBOARD] ERROR: No free port found. Exiting.")
                import sys

                sys.exit(1)
            print(f"[DASHBOARD] Auto-selected port: {port}")

    print(f"[DASHBOARD] Starting on http://{host}:{port}")
    app.run(host=host, port=port, debug=False)
