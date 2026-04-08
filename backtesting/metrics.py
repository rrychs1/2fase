"""
Performance metrics calculator for backtesting results.
"""

import numpy as np
import pandas as pd
from dataclasses import dataclass
from typing import List

from backtesting.sim_broker import SimTrade


@dataclass
class BacktestMetrics:
    """All calculated backtest performance metrics."""

    total_return_pct: float
    total_pnl: float
    sharpe_ratio: float
    max_drawdown_pct: float
    max_drawdown_abs: float
    win_rate: float
    profit_factor: float
    total_trades: int
    winning_trades: int
    losing_trades: int
    avg_trade_pnl: float
    avg_winner: float
    avg_loser: float
    max_consecutive_losses: int
    calmar_ratio: float
    buy_and_hold_return_pct: float
    initial_equity: float
    final_equity: float
    peak_equity: float


def calculate_metrics(
    equity_curve: List[float],
    trades: List[SimTrade],
    initial_equity: float,
    buy_hold_start_price: float,
    buy_hold_end_price: float,
    candles_per_day: float = 6.0,  # 4h candles = 6 per day
) -> BacktestMetrics:
    """
    Calculate comprehensive performance metrics.

    Args:
        equity_curve: List of equity values at each candle
        trades: List of completed SimTrade objects
        initial_equity: Starting balance
        buy_hold_start_price: Price at start of backtest
        buy_hold_end_price: Price at end of backtest
        candles_per_day: Number of candles per day (for annualization)
    """
    equity = np.array(equity_curve, dtype=float)
    final_equity = equity[-1] if len(equity) > 0 else initial_equity

    # --- Return ---
    total_pnl = final_equity - initial_equity
    total_return_pct = (total_pnl / initial_equity) * 100

    # --- Sharpe Ratio (annualized) ---
    if len(equity) > 1:
        returns = np.diff(equity) / equity[:-1]
        returns = returns[np.isfinite(returns)]
        if len(returns) > 0 and np.std(returns) > 0:
            candles_per_year = candles_per_day * 365
            sharpe_ratio = (np.mean(returns) / np.std(returns)) * np.sqrt(
                candles_per_year
            )
        else:
            sharpe_ratio = 0.0
    else:
        sharpe_ratio = 0.0

    # --- Max Drawdown ---
    peak = np.maximum.accumulate(equity)
    drawdown = (peak - equity) / peak
    drawdown_abs = peak - equity
    max_drawdown_pct = float(np.max(drawdown)) * 100 if len(drawdown) > 0 else 0.0
    max_drawdown_abs = float(np.max(drawdown_abs)) if len(drawdown_abs) > 0 else 0.0
    peak_equity = float(np.max(equity)) if len(equity) > 0 else initial_equity

    # --- Trade Statistics ---
    total_trades = len(trades)
    if total_trades > 0:
        pnls = [t.pnl_after_fees for t in trades]
        winners = [p for p in pnls if p > 0]
        losers = [p for p in pnls if p <= 0]

        winning_trades = len(winners)
        losing_trades = len(losers)
        win_rate = (winning_trades / total_trades) * 100

        avg_trade_pnl = sum(pnls) / total_trades
        avg_winner = sum(winners) / winning_trades if winners else 0.0
        avg_loser = sum(losers) / losing_trades if losers else 0.0

        gross_profit = sum(winners) if winners else 0.0
        gross_loss = abs(sum(losers)) if losers else 0.001  # Avoid div by zero
        profit_factor = gross_profit / gross_loss

        # Max consecutive losses
        max_consec = 0
        current_streak = 0
        for p in pnls:
            if p <= 0:
                current_streak += 1
                max_consec = max(max_consec, current_streak)
            else:
                current_streak = 0
        max_consecutive_losses = max_consec
    else:
        winning_trades = losing_trades = 0
        win_rate = avg_trade_pnl = avg_winner = avg_loser = 0.0
        profit_factor = 0.0
        max_consecutive_losses = 0

    # --- Calmar Ratio ---
    if len(equity) > 1:
        trading_days = len(equity) / candles_per_day
        annual_return = (
            (total_return_pct / 100) * (365 / trading_days) if trading_days > 0 else 0.0
        )
        calmar_ratio = (
            annual_return / (max_drawdown_pct / 100) if max_drawdown_pct > 0 else 0.0
        )
    else:
        calmar_ratio = 0.0

    # --- Buy & Hold ---
    buy_and_hold_return_pct = (
        (buy_hold_end_price - buy_hold_start_price) / buy_hold_start_price
    ) * 100

    return BacktestMetrics(
        total_return_pct=round(total_return_pct, 2),
        total_pnl=round(total_pnl, 2),
        sharpe_ratio=round(sharpe_ratio, 3),
        max_drawdown_pct=round(max_drawdown_pct, 2),
        max_drawdown_abs=round(max_drawdown_abs, 2),
        win_rate=round(win_rate, 1),
        profit_factor=round(profit_factor, 3),
        total_trades=total_trades,
        winning_trades=winning_trades,
        losing_trades=losing_trades,
        avg_trade_pnl=round(avg_trade_pnl, 2),
        avg_winner=round(avg_winner, 2),
        avg_loser=round(avg_loser, 2),
        max_consecutive_losses=max_consecutive_losses,
        calmar_ratio=round(calmar_ratio, 3),
        buy_and_hold_return_pct=round(buy_and_hold_return_pct, 2),
        initial_equity=initial_equity,
        final_equity=round(final_equity, 2),
        peak_equity=round(peak_equity, 2),
    )


def print_metrics(metrics: BacktestMetrics):
    """Pretty-print metrics to console."""
    print("\n" + "=" * 60)
    print("         BACKTEST RESULTS")
    print("=" * 60)
    print(f"  Initial Equity:      ${metrics.initial_equity:>12,.2f}")
    print(f"  Final Equity:        ${metrics.final_equity:>12,.2f}")
    print(f"  Peak Equity:         ${metrics.peak_equity:>12,.2f}")
    print(f"  Total PnL:           ${metrics.total_pnl:>12,.2f}")
    print(f"  Total Return:         {metrics.total_return_pct:>11.2f}%")
    print(f"  Buy & Hold Return:    {metrics.buy_and_hold_return_pct:>11.2f}%")
    print("-" * 60)
    print(f"  Sharpe Ratio:         {metrics.sharpe_ratio:>11.3f}")
    print(
        f"  Max Drawdown:         {metrics.max_drawdown_pct:>11.2f}%  (${metrics.max_drawdown_abs:,.2f})"
    )
    print(f"  Calmar Ratio:         {metrics.calmar_ratio:>11.3f}")
    print("-" * 60)
    print(f"  Total Trades:         {metrics.total_trades:>11d}")
    print(f"  Win Rate:             {metrics.win_rate:>11.1f}%")
    print(f"  Profit Factor:        {metrics.profit_factor:>11.3f}")
    print(f"  Avg Trade PnL:       ${metrics.avg_trade_pnl:>12,.2f}")
    print(f"  Avg Winner:          ${metrics.avg_winner:>12,.2f}")
    print(f"  Avg Loser:           ${metrics.avg_loser:>12,.2f}")
    print(f"  Max Consec. Losses:   {metrics.max_consecutive_losses:>11d}")
    print("=" * 60 + "\n")
