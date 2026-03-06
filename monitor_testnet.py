# -*- coding: utf-8 -*-
import io, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
"""
monitor_testnet.py - Resumen de la sesion de Testnet.
Ejecutar: python monitor_testnet.py
"""
import json
import sqlite3
import os
from datetime import date, datetime

DB_PATH = "data/trading_v3.db"
STATE_PATH = "status.json"
RISK_PATH  = "risk_state.json"

def print_header(title):
    print("\n" + "=" * 50)
    print(f"  {title}")
    print("=" * 50)

def load_json(path):
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return {}

# ── 1. Bot status ────────────────────────────────────
print_header("ESTADO DEL BOT")
status = load_json(STATE_PATH)
risk   = load_json(RISK_PATH)

print(f"  Estado:       {status.get('status', 'desconocido')}")
print(f"  Modo:         {status.get('mode', 'desconocido')}")
print(f"  Uptime:       {status.get('uptime', 'N/A')}")
print(f"  Último loop:  {status.get('last_loop', 'N/A')}")
print(f"  Kill Switch:  {'[ACTIVO]' if risk.get('is_kill_switch_active') else '[OK]'}")
print(f"  Equity ref.:  {risk.get('day_start_equity', 0):.2f} USDT")

# ── 2. Trades del día ────────────────────────────────
print_header("TRADES DE HOY")
today_str = str(date.today())
try:
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT * FROM trades WHERE closed_at LIKE ? ORDER BY closed_at DESC", (f"{today_str}%",))
        trades = cur.fetchall()

    if not trades:
        print("  Sin trades registrados hoy.")
    else:
        total_pnl = sum(float(t["realized_pnl"]) for t in trades)
        wins = sum(1 for t in trades if float(t["realized_pnl"]) > 0)
        print(f"  Trades hoy:   {len(trades)}")
        print(f"  Ganados:      {wins}  |  Perdidos: {len(trades)-wins}")
        print(f"  PnL neto:     {total_pnl:+.4f} USDT")
        print(f"\n  {'ID':<15}  {'SYMBOL':<10}  {'SIDE':<5}  {'PnL':>10}")
        print(f"  {'-'*50}")
        for t in trades[:10]:
            print(f"  {str(t['trade_id']):<15}  {t['symbol']:<10}  {t['side']:<5}  {float(t['realized_pnl']):>+10.4f}")
except Exception as e:
    print(f"  Error al consultar BD: {e}")

# ── 3. Stats globales ────────────────────────────────
print_header("STATS GLOBALES")
try:
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*), SUM(realized_pnl), MAX(realized_pnl), MIN(realized_pnl) FROM trades")
        total, pnl_sum, best, worst = cur.fetchone()
        cur.execute("SELECT COUNT(*) FROM trades WHERE realized_pnl > 0")
        wins_all = cur.fetchone()[0]
        wr = (wins_all / total * 100) if total else 0
    print(f"  Total trades: {total}")
    print(f"  PnL total:    {(pnl_sum or 0):+.4f} USDT")
    print(f"  Win rate:     {wr:.1f}%")
    print(f"  Mejor trade:  {(best or 0):+.4f} USDT")
    print(f"  Peor trade:   {(worst or 0):+.4f} USDT")
except Exception as e:
    print(f"  Error al consultar stats: {e}")

print()
