"""
HTML report generator for backtesting results.
Creates standalone HTML with embedded base64 charts using matplotlib.
"""
import os
import io
import base64
import logging
from datetime import datetime
from typing import List

import numpy as np
import matplotlib
matplotlib.use("Agg")  # Non-interactive backend
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

from backtesting.metrics import BacktestMetrics
from backtesting.sim_broker import SimTrade

logger = logging.getLogger(__name__)

REPORTS_DIR = os.path.join(os.path.dirname(__file__), "reports")


def _fig_to_base64(fig) -> str:
    """Convert matplotlib figure to base64 encoded PNG."""
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=120, bbox_inches="tight", facecolor="#1a1a2e")
    buf.seek(0)
    b64 = base64.b64encode(buf.read()).decode("utf-8")
    plt.close(fig)
    return b64


def _plot_equity_curve(equity_curve: List[float], buy_hold_curve: List[float]) -> str:
    """Equity curve vs Buy & Hold."""
    fig, ax = plt.subplots(figsize=(12, 5))
    fig.patch.set_facecolor("#1a1a2e")
    ax.set_facecolor("#16213e")

    x = range(len(equity_curve))
    ax.plot(x, equity_curve, color="#00d2ff", linewidth=1.5, label="Strategy", zorder=3)
    if buy_hold_curve:
        ax.plot(x, buy_hold_curve, color="#ff6b6b", linewidth=1.0, alpha=0.7, label="Buy & Hold", zorder=2)

    ax.fill_between(x, equity_curve, alpha=0.1, color="#00d2ff")
    ax.set_title("Equity Curve", color="white", fontsize=14, fontweight="bold")
    ax.set_xlabel("Candles", color="#aaa")
    ax.set_ylabel("Equity ($)", color="#aaa")
    ax.tick_params(colors="#888")
    ax.legend(facecolor="#16213e", edgecolor="#333", labelcolor="white")
    ax.grid(True, alpha=0.15, color="#444")
    for spine in ax.spines.values():
        spine.set_color("#333")

    return _fig_to_base64(fig)


def _plot_drawdown(equity_curve: List[float]) -> str:
    """Drawdown chart."""
    fig, ax = plt.subplots(figsize=(12, 3))
    fig.patch.set_facecolor("#1a1a2e")
    ax.set_facecolor("#16213e")

    equity = np.array(equity_curve)
    peak = np.maximum.accumulate(equity)
    drawdown = ((peak - equity) / peak) * 100

    ax.fill_between(range(len(drawdown)), 0, -drawdown, color="#ff6b6b", alpha=0.5)
    ax.plot(range(len(drawdown)), -drawdown, color="#ff6b6b", linewidth=0.8)
    ax.set_title("Drawdown (%)", color="white", fontsize=14, fontweight="bold")
    ax.set_xlabel("Candles", color="#aaa")
    ax.set_ylabel("Drawdown %", color="#aaa")
    ax.tick_params(colors="#888")
    ax.grid(True, alpha=0.15, color="#444")
    for spine in ax.spines.values():
        spine.set_color("#333")

    return _fig_to_base64(fig)


def _plot_trade_pnl(trades: List[SimTrade]) -> str:
    """Trade PnL distribution histogram."""
    fig, ax = plt.subplots(figsize=(10, 4))
    fig.patch.set_facecolor("#1a1a2e")
    ax.set_facecolor("#16213e")

    if not trades:
        ax.text(0.5, 0.5, "No Trades", ha="center", va="center", color="white", fontsize=16)
        return _fig_to_base64(fig)

    pnls = [t.pnl_after_fees for t in trades]
    colors = ["#00c853" if p > 0 else "#ff1744" for p in pnls]

    ax.bar(range(len(pnls)), pnls, color=colors, alpha=0.8, width=0.8)
    ax.axhline(y=0, color="#666", linewidth=0.5)
    ax.set_title("Trade PnL Distribution", color="white", fontsize=14, fontweight="bold")
    ax.set_xlabel("Trade #", color="#aaa")
    ax.set_ylabel("PnL ($)", color="#aaa")
    ax.tick_params(colors="#888")
    ax.grid(True, alpha=0.15, color="#444", axis="y")
    for spine in ax.spines.values():
        spine.set_color("#333")

    return _fig_to_base64(fig)


def _plot_cumulative_pnl(trades: List[SimTrade]) -> str:
    """Cumulative PnL from trades."""
    fig, ax = plt.subplots(figsize=(10, 4))
    fig.patch.set_facecolor("#1a1a2e")
    ax.set_facecolor("#16213e")

    if not trades:
        ax.text(0.5, 0.5, "No Trades", ha="center", va="center", color="white", fontsize=16)
        return _fig_to_base64(fig)

    cum_pnl = np.cumsum([t.pnl_after_fees for t in trades])
    ax.plot(range(len(cum_pnl)), cum_pnl, color="#7c4dff", linewidth=2)
    ax.fill_between(range(len(cum_pnl)), cum_pnl, alpha=0.15, color="#7c4dff")
    ax.axhline(y=0, color="#666", linewidth=0.5)
    ax.set_title("Cumulative Trade PnL", color="white", fontsize=14, fontweight="bold")
    ax.set_xlabel("Trade #", color="#aaa")
    ax.set_ylabel("Cumulative PnL ($)", color="#aaa")
    ax.tick_params(colors="#888")
    ax.grid(True, alpha=0.15, color="#444")
    for spine in ax.spines.values():
        spine.set_color("#333")

    return _fig_to_base64(fig)


def generate_report(
    metrics: BacktestMetrics,
    equity_curve: List[float],
    trades: List[SimTrade],
    symbol: str,
    timeframe: str,
    start_date: str,
    end_date: str,
    initial_balance: float,
) -> str:
    """
    Generate a standalone HTML report.

    Returns:
        Path to the generated HTML file.
    """
    os.makedirs(REPORTS_DIR, exist_ok=True)

    # Build buy & hold curve for comparison
    if len(equity_curve) > 1:
        ratio = initial_balance / (equity_curve[0] if equity_curve[0] > 0 else 1)
        # Simple buy & hold: scale initial equity by price change
        start_eq = equity_curve[0]
        buy_hold_curve = [start_eq]
        # We'll approximate buy & hold as linear from initial to final based on return
        bh_return = metrics.buy_and_hold_return_pct / 100
        for i in range(1, len(equity_curve)):
            progress = i / (len(equity_curve) - 1)
            buy_hold_curve.append(initial_balance * (1 + bh_return * progress))
    else:
        buy_hold_curve = []

    # Generate charts
    equity_chart = _plot_equity_curve(equity_curve, buy_hold_curve)
    drawdown_chart = _plot_drawdown(equity_curve)
    trade_pnl_chart = _plot_trade_pnl(trades)
    cumulative_chart = _plot_cumulative_pnl(trades)

    # Metric color helpers
    def _color(val, threshold=0, invert=False):
        if invert:
            return "#00c853" if val < threshold else "#ff1744"
        return "#00c853" if val > threshold else "#ff1744"

    ret_color = _color(metrics.total_return_pct)
    sharpe_color = _color(metrics.sharpe_ratio, 1.0)
    dd_color = _color(metrics.max_drawdown_pct, 15, invert=True)
    wr_color = _color(metrics.win_rate, 50)
    pf_color = _color(metrics.profit_factor, 1.0)

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    safe_symbol = symbol.replace("/", "-")
    filename = f"backtest_{safe_symbol}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
    filepath = os.path.join(REPORTS_DIR, filename)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Backtest Report — {symbol}</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{
    font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
    background: #0f0f23;
    color: #e0e0e0;
    padding: 24px;
    line-height: 1.6;
  }}
  .container {{ max-width: 1100px; margin: 0 auto; }}
  h1 {{
    font-size: 28px;
    background: linear-gradient(135deg, #00d2ff, #7c4dff);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    margin-bottom: 4px;
  }}
  .subtitle {{ color: #888; font-size: 14px; margin-bottom: 24px; }}
  .metrics-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
    gap: 16px;
    margin-bottom: 32px;
  }}
  .metric-card {{
    background: #1a1a2e;
    border: 1px solid #2a2a4a;
    border-radius: 12px;
    padding: 16px;
    text-align: center;
  }}
  .metric-card .label {{ font-size: 12px; color: #888; text-transform: uppercase; letter-spacing: 1px; }}
  .metric-card .value {{ font-size: 24px; font-weight: 700; margin-top: 4px; }}
  .chart-section {{
    background: #1a1a2e;
    border: 1px solid #2a2a4a;
    border-radius: 12px;
    padding: 16px;
    margin-bottom: 20px;
  }}
  .chart-section img {{ width: 100%; border-radius: 8px; }}
  .trades-table {{
    width: 100%;
    border-collapse: collapse;
    margin-top: 16px;
    font-size: 13px;
  }}
  .trades-table th {{
    background: #16213e;
    color: #aaa;
    text-transform: uppercase;
    font-size: 11px;
    letter-spacing: 0.5px;
    padding: 10px 8px;
    text-align: left;
    border-bottom: 1px solid #2a2a4a;
  }}
  .trades-table td {{
    padding: 8px;
    border-bottom: 1px solid #1a1a2e;
  }}
  .trades-table tr:hover {{ background: #16213e; }}
  .positive {{ color: #00c853; }}
  .negative {{ color: #ff1744; }}
  footer {{ text-align: center; color: #555; font-size: 12px; margin-top: 32px; }}
</style>
</head>
<body>
<div class="container">

<h1>📊 Backtest Report</h1>
<p class="subtitle">{symbol} | {timeframe} | {start_date} → {end_date} | Generated: {timestamp}</p>

<div class="metrics-grid">
  <div class="metric-card">
    <div class="label">Total Return</div>
    <div class="value" style="color: {ret_color}">{metrics.total_return_pct:+.2f}%</div>
  </div>
  <div class="metric-card">
    <div class="label">Buy & Hold</div>
    <div class="value" style="color: {_color(metrics.buy_and_hold_return_pct)}">{metrics.buy_and_hold_return_pct:+.2f}%</div>
  </div>
  <div class="metric-card">
    <div class="label">Sharpe Ratio</div>
    <div class="value" style="color: {sharpe_color}">{metrics.sharpe_ratio:.3f}</div>
  </div>
  <div class="metric-card">
    <div class="label">Max Drawdown</div>
    <div class="value" style="color: {dd_color}">{metrics.max_drawdown_pct:.2f}%</div>
  </div>
  <div class="metric-card">
    <div class="label">Win Rate</div>
    <div class="value" style="color: {wr_color}">{metrics.win_rate:.1f}%</div>
  </div>
  <div class="metric-card">
    <div class="label">Profit Factor</div>
    <div class="value" style="color: {pf_color}">{metrics.profit_factor:.3f}</div>
  </div>
  <div class="metric-card">
    <div class="label">Total Trades</div>
    <div class="value">{metrics.total_trades}</div>
  </div>
  <div class="metric-card">
    <div class="label">Final Equity</div>
    <div class="value">${metrics.final_equity:,.2f}</div>
  </div>
</div>

<div class="chart-section">
  <img src="data:image/png;base64,{equity_chart}" alt="Equity Curve">
</div>

<div class="chart-section">
  <img src="data:image/png;base64,{drawdown_chart}" alt="Drawdown">
</div>

<div class="chart-section">
  <img src="data:image/png;base64,{trade_pnl_chart}" alt="Trade PnL">
</div>

<div class="chart-section">
  <img src="data:image/png;base64,{cumulative_chart}" alt="Cumulative PnL">
</div>

<div class="chart-section">
  <h3 style="color: #ccc; margin-bottom: 12px;">📋 Detailed Metrics</h3>
  <table class="trades-table">
    <tr><td>Initial Equity</td><td>${metrics.initial_equity:,.2f}</td></tr>
    <tr><td>Final Equity</td><td style="color: {ret_color}">${metrics.final_equity:,.2f}</td></tr>
    <tr><td>Peak Equity</td><td>${metrics.peak_equity:,.2f}</td></tr>
    <tr><td>Total PnL</td><td style="color: {ret_color}">${metrics.total_pnl:,.2f}</td></tr>
    <tr><td>Total Return</td><td style="color: {ret_color}">{metrics.total_return_pct:+.2f}%</td></tr>
    <tr><td>Buy & Hold Return</td><td>{metrics.buy_and_hold_return_pct:+.2f}%</td></tr>
    <tr><td>Sharpe Ratio</td><td>{metrics.sharpe_ratio:.3f}</td></tr>
    <tr><td>Max Drawdown</td><td>{metrics.max_drawdown_pct:.2f}% (${metrics.max_drawdown_abs:,.2f})</td></tr>
    <tr><td>Calmar Ratio</td><td>{metrics.calmar_ratio:.3f}</td></tr>
    <tr><td>Total Trades</td><td>{metrics.total_trades}</td></tr>
    <tr><td>Winning Trades</td><td class="positive">{metrics.winning_trades}</td></tr>
    <tr><td>Losing Trades</td><td class="negative">{metrics.losing_trades}</td></tr>
    <tr><td>Win Rate</td><td>{metrics.win_rate:.1f}%</td></tr>
    <tr><td>Profit Factor</td><td>{metrics.profit_factor:.3f}</td></tr>
    <tr><td>Avg Trade PnL</td><td>${metrics.avg_trade_pnl:,.2f}</td></tr>
    <tr><td>Avg Winner</td><td class="positive">${metrics.avg_winner:,.2f}</td></tr>
    <tr><td>Avg Loser</td><td class="negative">${metrics.avg_loser:,.2f}</td></tr>
    <tr><td>Max Consec. Losses</td><td>{metrics.max_consecutive_losses}</td></tr>
  </table>
</div>

{"" if not trades else _render_trades_table(trades)}

<footer>
  Generated by Binance Futures Trading Bot — Backtesting Module
</footer>

</div>
</body>
</html>"""

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(html)

    logger.info(f"Report saved to {filepath}")
    return filepath


def _render_trades_table(trades: List[SimTrade]) -> str:
    """Render the trade log table."""
    rows = ""
    for i, t in enumerate(trades):
        pnl_class = "positive" if t.pnl_after_fees > 0 else "negative"
        rows += f"""<tr>
  <td>{i + 1}</td>
  <td>{t.symbol}</td>
  <td>{t.side}</td>
  <td>${t.entry_price:,.2f}</td>
  <td>${t.exit_price:,.2f}</td>
  <td>{t.amount:.4f}</td>
  <td class="{pnl_class}">${t.pnl_after_fees:,.2f}</td>
  <td>${t.fees:,.2f}</td>
</tr>"""

    return f"""
<div class="chart-section">
  <h3 style="color: #ccc; margin-bottom: 12px;">📝 Trade Log ({len(trades)} trades)</h3>
  <div style="max-height: 400px; overflow-y: auto;">
  <table class="trades-table">
    <thead>
      <tr>
        <th>#</th><th>Symbol</th><th>Side</th><th>Entry</th>
        <th>Exit</th><th>Amount</th><th>PnL</th><th>Fees</th>
      </tr>
    </thead>
    <tbody>{rows}</tbody>
  </table>
  </div>
</div>"""
