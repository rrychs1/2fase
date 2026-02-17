import json
import os
import pandas as pd
from datetime import datetime

def analyze_performance():
    account_file = "virtual_account.json"
    papers_file = "papers.jsonl"
    
    print("=== BINANCE BOT PERFORMANCE ANALYST ===")
    
    if os.path.exists(account_file):
        with open(account_file, "r") as f:
            state = json.load(f)
            
        print(f"\n[VIRTUAL ACCOUNT]")
        print(f"Current Balance: ${state['balance']:,.2f}")
        print(f"Equity: ${state.get('equity', 0.0):,.2f}")
        print(f"Open Positions: {len(state['positions'])}")
        for sym, pos in state['positions'].items():
            print(f"  - {sym}: {pos['side']} {pos['amount']:.4f} @ {pos['average_price']:.2f} (Avg)")
            
        pending = state.get('pending_orders', [])
        if pending:
            print(f"\n[PENDING ORDERS] ({len(pending)})")
            # Show first 5 for brevity
            for p in pending[:5]:
                print(f"  - {p['symbol']}: {p['side']} @ {p['price']:.2f} ({p.get('type','limit')})")
            if len(pending) > 5:
                print(f"  ... and {len(pending)-5} more.")
            
        history = state.get('history', [])
        if history:
            df_hist = pd.DataFrame(history)
            total_pnl = df_hist['pnl'].sum()
            win_rate = (df_hist['pnl'] > 0).mean() * 100
            print(f"\n[CLOSED TRADES]")
            print(f"Total Trades: {len(history)}")
            print(f"Total PnL: ${total_pnl:,.2f}")
            print(f"Win Rate: {win_rate:.1f}%")
            print(f"Best Trade: ${df_hist['pnl'].max():,.2f}")
            print(f"Worst Trade: ${df_hist['pnl'].min():,.2f}")
    else:
        print("\n[!] virtual_account.json not found yet.")

    if os.path.exists(papers_file):
        print(f"\n[MARKET REGIME SUMMARY]")
        data = []
        with open(papers_file, "r") as f:
            for line in f:
                data.append(json.loads(line))
        
        df_papers = pd.DataFrame(data)
        if not df_papers.empty:
            regime_counts = df_papers['regime'].value_counts()
            for regime, count in regime_counts.items():
                print(f"  - {regime}: {count} iterations")
            
            avg_signals = df_papers['signals_count'].mean()
            print(f"  - Avg Signals per loop: {avg_signals:.2f}")

if __name__ == "__main__":
    analyze_performance()
