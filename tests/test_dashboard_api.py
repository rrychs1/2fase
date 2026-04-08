"""
Dashboard API smoke tests — validates all endpoints return correct schemas.

Usage:
    1. Seed data:    python tests/seed_dashboard_data.py
    2. Start server: python run_dashboard.py --no-browser  (in another terminal)
    3. Run tests:    python tests/test_dashboard_api.py

All tests hit the live Flask server and validate response schemas.
"""

import sys
import os
import json
import urllib.request
import urllib.error

# Project root (for --refresh)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

BASE = "http://127.0.0.1:5050"
PASS = 0
FAIL = 0


def check(name, url, required_keys, extra_checks=None):
    """Fetch a URL, validate keys exist, run optional checks."""
    global PASS, FAIL
    try:
        resp = urllib.request.urlopen(f"{BASE}{url}", timeout=5)
        data = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print(f"  [FAIL] {name}: {e}")
        FAIL += 1
        return

    # Check required keys
    missing = [k for k in required_keys if k not in data]
    if missing:
        print(f"  [FAIL] {name}: Missing keys: {missing}")
        FAIL += 1
        return

    # Run extra checks
    if extra_checks:
        for desc, fn in extra_checks:
            try:
                result = fn(data)
                if not result:
                    print(f"  [FAIL] {name}: {desc}")
                    FAIL += 1
                    return
            except Exception as e:
                print(f"  [FAIL] {name}: {desc} -> {e}")
                FAIL += 1
                return

    print(f"  [PASS] {name}")
    PASS += 1


def main():
    # --refresh: re-stamp the state file so freshness checks pass
    if "--refresh" in sys.argv:
        from state.state_manager import write_bot_state, load_bot_state

        state_path = os.path.join(ROOT, "data", "dashboard_state.json")
        state = load_bot_state(state_path)
        if state:
            state.pop("timestamp", None)  # write_bot_state will inject now()
            write_bot_state(state_path, state)
            print("  [*] Refreshed dashboard_state.json timestamp")
        status_path = os.path.join(ROOT, "status.json")
        s = load_bot_state(status_path)
        if s:
            s.pop("timestamp", None)
            write_bot_state(status_path, s)
            print("  [*] Refreshed status.json timestamp")

    print(f"\n=== Dashboard API Tests ({BASE}) ===\n")

    # ── /dashboard/health ────────────────────────────────────
    check(
        "/dashboard/health",
        "/dashboard/health",
        [
            "status",
            "timestamp",
            "can_read_bot_state",
            "database_ok",
            "database_has_data",
        ],
        [
            ("status is healthy", lambda d: d["status"] == "healthy"),
            ("can_read_bot_state=true", lambda d: d["can_read_bot_state"] is True),
            ("database_ok=true", lambda d: d["database_ok"] is True),
            ("database_has_data=true", lambda d: d["database_has_data"] is True),
        ],
    )

    # ── /api/state ───────────────────────────────────────────
    check(
        "/api/state",
        "/api/state",
        [
            "running",
            "mode",
            "iteration",
            "last_loop_ts",
            "equity",
            "open_positions",
            "pending_orders",
            "history",
            "regimes",
            "prices",
            "last_error",
            "exchange_status",
            "has_data",
        ],
        [
            ("has_data=true", lambda d: d["has_data"] is True),
            ("running=true", lambda d: d["running"] is True),
            ("mode is Paper", lambda d: d["mode"] == "Paper"),
            ("iteration > 0", lambda d: d["iteration"] > 0),
            ("equity > 0", lambda d: d["equity"] > 0),
            ("has positions", lambda d: len(d["open_positions"]) > 0),
            ("has pending orders", lambda d: len(d["pending_orders"]) > 0),
            ("has trade history", lambda d: len(d["history"]) > 0),
            ("has regimes", lambda d: len(d["regimes"]) > 0),
            ("has prices", lambda d: len(d["prices"]) > 0),
            ("last_loop_ts is ISO string", lambda d: "T" in str(d["last_loop_ts"])),
        ],
    )

    # ── /api/metrics ─────────────────────────────────────────
    check(
        "/api/metrics",
        "/api/metrics",
        [
            "has_data",
            "balance",
            "equity",
            "unrealized_pnl",
            "total_pnl",
            "total_trades",
            "win_rate",
        ],
        [
            ("has_data=true", lambda d: d["has_data"] is True),
            ("balance > 0", lambda d: d["balance"] > 0),
            ("equity > 0", lambda d: d["equity"] > 0),
            ("total_trades > 0", lambda d: d["total_trades"] > 0),
            ("win_rate > 0", lambda d: d["win_rate"] > 0),
            (
                "total_pnl is a number",
                lambda d: isinstance(d["total_pnl"], (int, float)),
            ),
        ],
    )

    # ── /api/equity-history ──────────────────────────────────
    check(
        "/api/equity-history",
        "/api/equity-history",
        [],  # Returns an array, not dict
        [
            ("returns array", lambda d: isinstance(d, list)),
            ("has >= 10 points", lambda d: len(d) >= 10),
            ("points have ts field", lambda d: "ts" in d[0]),
            ("points have equity field", lambda d: "equity" in d[0]),
        ],
    )

    # ── /api/logs ────────────────────────────────────────────
    check(
        "/api/logs",
        "/api/logs",
        [],
        [
            ("returns array", lambda d: isinstance(d, list)),
            ("has log lines", lambda d: len(d) > 0),
        ],
    )

    # ── /api/alerts ──────────────────────────────────────────
    check(
        "/api/alerts",
        "/api/alerts",
        [],
        [
            ("returns array", lambda d: isinstance(d, list)),
            ("has alerts", lambda d: len(d) > 0),
            ("alerts have level", lambda d: "level" in d[0]),
            ("alerts have msg", lambda d: "msg" in d[0]),
        ],
    )

    # ── Legacy endpoints still work ─────────────────────────
    check(
        "/api/status (legacy)",
        "/api/status",
        ["status", "is_active", "mode"],
        [("status is Running", lambda d: d["status"] == "Running")],
    )

    check(
        "/api/account (legacy)",
        "/api/account",
        ["balance", "equity", "total_trades", "has_data"],
        [("balance > 0", lambda d: d["balance"] > 0)],
    )

    # ── Summary ──────────────────────────────────────────────
    total = PASS + FAIL
    print(f"\n{'=' * 40}")
    print(f"  Results: {PASS}/{total} passed", end="")
    if FAIL > 0:
        print(f"  ({FAIL} FAILED)")
        sys.exit(1)
    else:
        print("  [+] ALL GREEN")
        sys.exit(0)


if __name__ == "__main__":
    main()
