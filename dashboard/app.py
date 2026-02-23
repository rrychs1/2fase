"""
Trading Bot Dashboard — Flask backend.
Reads unified dashboard_state.json + papers.jsonl + logs.
"""
import json
import os
from flask import Flask, render_template, jsonify
from collections import deque

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

app = Flask(__name__)

# ─────────────────────────────────────────── helpers ──────────
def _read_json(filename):
    path = os.path.join(BASE_DIR, filename)
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _read_jsonl(filename, max_lines=500):
    path = os.path.join(BASE_DIR, filename)
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


def _read_log_tail(filename="logs/bot.log", n=80):
    path = os.path.join(BASE_DIR, filename)
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
    state = _read_json("dashboard_state.json")
    if state:
        return jsonify({
            "status": "Running",
            "uptime": state.get("uptime", "--"),
            "mode": state.get("mode", "Unknown"),
            "last_loop": state.get("timestamp", ""),
            "iteration": state.get("iteration", 0),
        })
    return jsonify(_read_json("status.json"))


@app.route("/api/account")
def api_account():
    # Read from unified dashboard_state.json (written by bot each iteration)
    state = _read_json("dashboard_state.json")

    if not state:
        # Fallback to legacy virtual_account.json
        state = _read_json("virtual_account.json")

    history = state.get("history", [])
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
    records = _read_jsonl("papers.jsonl", max_lines=1000)
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
    lines = _read_log_tail()
    return jsonify(lines)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5050, debug=False)
