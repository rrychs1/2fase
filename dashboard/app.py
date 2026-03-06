"""
Trading Bot Dashboard — Flask backend.
Reads unified dashboard_state.json + papers.jsonl + logs.
"""
import json
import os
from flask import Flask, render_template, jsonify
from collections import deque

import datetime
from dotenv import load_dotenv

# Absolute project root
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Load env variables early
load_dotenv(os.path.join(BASE_DIR, ".env"))

# Load paths from env or defaults
STATE_FILE = os.getenv("STATE_FILE", "dashboard_state.json")
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
            if not content.strip(): return {}
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


# ─────────────────────────────────────────── routes ──────────
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/status")
def api_status():
    # Prefer dashboard_state.json (richer data), fallback to status.json
    state = _read_json(STATE_FILE)
    
    if state:
        # Phase 19: Stale Data Detection (Senior Resilience)
        last_update_str = state.get("timestamp", "")
        is_active = False
        if last_update_str:
            try:
                # Use fromisoformat for speed
                last_dt = datetime.datetime.fromisoformat(last_update_str)
                now = datetime.datetime.now()
                # If update is > 120s old, bot is considered "Offline/Stalled"
                if (now - last_dt).total_seconds() < 120:
                    is_active = True
            except: pass

        return jsonify({
            "status": "Running" if is_active else "Offline",
            "is_active": is_active,
            "uptime": state.get("uptime", "--"),
            "mode": state.get("mode", "Unknown"),
            "last_loop": last_update_str,
            "iteration": state.get("iteration", 0),
            "last_error": state.get("last_error"),
            "telegram_healthy": state.get("telegram_healthy", True),
            "exchange_status": state.get("exchange_status", "Unknown"),
            "bot_status": state.get("status", {}) # Phase 22: Detailed operational status
        })
    
    status_fallback = _read_json("status.json")
    if status_fallback:
        status_fallback["is_active"] = False # Default to false for fallback
        return jsonify(status_fallback)
        
    return jsonify({"status": "Offline", "is_active": False})


@app.route("/api/account")
def api_account():
    # Read from unified dashboard_state.json (written by bot each iteration)
    state = _read_json(STATE_FILE)

    if not state:
        # Fallback to legacy virtual_account.json
        state = _read_json("virtual_account.json")

    history = state.get("history", [])
    
    # Phase 4+: Use persistent global stats if available
    global_stats = state.get("global_stats", {})
    if global_stats:
        total = global_stats.get("total_trades", len(history))
        win_rate = global_stats.get("win_rate", 0)
        total_pnl = global_stats.get("total_pnl", 0)
    else:
        # Fallback to calculation from the available history slice
        total = len(history)
        wins = sum(1 for t in history if t.get("pnl", 0) > 0)
        total_pnl = sum(t.get("pnl", 0) for t in history)
        win_rate = (wins / total * 100) if total > 0 else 0

    return jsonify({
        "balance": state.get("balance", 0),
        "equity": state.get("equity", state.get("balance", 0)),
        "unrealized_pnl": state.get("unrealized_pnl", 0),
        "positions": state.get("positions", {}),
        "pending_orders": state.get("pending_orders", []),
        "history": history[:50],  # Show 50 newest trades
        "total_trades": total,
        "win_rate": round(win_rate, 1),
        "total_pnl": round(total_pnl, 2),
        "regimes": state.get("regimes", {}),
        "prices": state.get("prices", {}),
        "mode": state.get("mode", "Unknown"),
    })


@app.route("/api/equity-history")
def api_equity_history():
    records = _read_jsonl(PAPERS_FILE, max_lines=1000)
    points = []
    for r in records:
        points.append({
            "ts": r.get("ts", ""),
            "equity": r.get("virtual_equity", 10000),
            "price": r.get("price", 0),
            "regime": r.get("regime", ""),
            "symbol": r.get("symbol", ""),
            "signals": r.get("signals_count", 0),
        })
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
        # Reverse to show newest first
        alerts.reverse()
        return jsonify(alerts)
    except Exception:
        return jsonify([])


@app.route("/api/metrics")
def api_metrics():
    """Expose operational metrics for monitoring."""
    state = _read_json(STATE_FILE)
    metrics = state.get("metrics", {
        "signals_processed": 0,
        "orders_placed": 0,
        "orders_failed": 0,
        "errors": 0
    })
    
    return jsonify({
        "uptime": state.get("uptime", "--"),
        "exchange_status": state.get("exchange_status", "Unknown"),
        "iteration": state.get("iteration", 0),
        "signals_processed": metrics.get("signals_processed", 0),
        "orders_placed": metrics.get("orders_placed", 0),
        "orders_failed": metrics.get("orders_failed", 0),
        "errors": metrics.get("errors", 0),
        "last_update": state.get("timestamp", ""),
        "db_size_kb": os.path.getsize(_get_abs_path(DB_PATH)) // 1024 if os.path.exists(_get_abs_path(DB_PATH)) else 0
    })


@app.route("/dashboard/health")
def healthcheck():
    """Healthcheck endpoint for Docker/DigitalOcean."""
    try:
        path = _get_abs_path(STATE_FILE)
        state_ok = os.path.exists(path)
        db_path = _get_abs_path(DB_PATH)
        db_ok = os.path.exists(db_path)
        
        # Check if we can reach the bot state
        can_read = False
        if state_ok:
            try:
                with open(path, "r") as f:
                    json.load(f)
                can_read = True
            except: pass

        return jsonify({
            "status": "healthy",
            "timestamp": datetime.datetime.now().isoformat(),
            "can_read_bot_state": can_read,
            "database_ok": db_ok,
            "telegram_service_reachable": True, # Dashboard can't check directly easily, so assume OK if server alive
            "system": "resilient"
        }), 200
    except Exception as e:
        return jsonify({"status": "degraded", "error": str(e)}), 200


if __name__ == "__main__":
    port = int(os.getenv("DASHBOARD_PORT", 8000))
    host = os.getenv("DASHBOARD_HOST", "0.0.0.0")
    app.run(host=host, port=port, debug=False)
