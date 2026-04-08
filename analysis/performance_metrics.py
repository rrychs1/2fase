import pandas as pd
import numpy as np
from typing import Dict, Union, List


class PerformanceMetrics:
    """
    Vectorized Performance Analytics Module using pandas and numpy.
    Supports calculating both equity curve time-series metrics and trade-based metrics.
    """

    @staticmethod
    def calculate_equity_metrics(
        equity_series: pd.Series,
        risk_free_rate: float = 0.0,
        annualization_factor: int = 365,
    ) -> Dict[str, float]:
        """
        Calculates time-series risk and return metrics from a daily equity curve.
        """
        if equity_series is None or len(equity_series) < 2:
            return _empty_equity_metrics()

        # Ensure it's a series
        if not isinstance(equity_series, pd.Series):
            equity_series = pd.Series(equity_series)

        # Filter flat/zero initial values if they exist before trading started
        equity_series = equity_series.loc[equity_series > 0]
        if len(equity_series) < 2:
            return _empty_equity_metrics()

        # Calculate periodic returns
        returns = equity_series.pct_change().dropna()
        if len(returns) == 0:
            return _empty_equity_metrics()

        # 1. Total Return
        initial_equity = equity_series.iloc[0]
        final_equity = equity_series.iloc[-1]
        total_return = (final_equity / initial_equity) - 1.0

        # 2. Annualized Return
        # Estimate days elapsed assuming daily data if index is not datetime, otherwise use exact timedelta
        if pd.api.types.is_datetime64_any_dtype(equity_series.index):
            days_elapsed = (equity_series.index[-1] - equity_series.index[0]).days
        else:
            days_elapsed = len(equity_series)

        if days_elapsed > 0:
            annualized_return = (1 + total_return) ** (
                annualization_factor / days_elapsed
            ) - 1.0
        else:
            annualized_return = total_return

        # 3. Maximum Drawdown
        rolling_max = equity_series.cummax()
        drawdowns = (equity_series - rolling_max) / rolling_max
        max_drawdown = drawdowns.min()

        # 4. Volatility (Annualized)
        daily_volatility = returns.std()
        annualized_volatility = daily_volatility * np.sqrt(annualization_factor)

        # 5. Sharpe Ratio
        mean_return = returns.mean()
        if daily_volatility > 0:
            sharpe_ratio = (
                (mean_return - risk_free_rate)
                / daily_volatility
                * np.sqrt(annualization_factor)
            )
        else:
            sharpe_ratio = 0.0

        # 6. Sortino Ratio (Downside deviation only)
        downside_returns = returns[returns < 0]
        downside_std = (
            np.sqrt(np.mean(downside_returns**2)) if len(downside_returns) > 0 else 0.0
        )

        if downside_std > 0:
            sortino_ratio = (
                (mean_return - risk_free_rate)
                / downside_std
                * np.sqrt(annualization_factor)
            )
        else:
            # If no losing days and positive return, Sortino is infinite
            sortino_ratio = np.inf if mean_return > 0 else 0.0

        # 7. Calmar Ratio
        if abs(max_drawdown) > 0:
            calmar_ratio = annualized_return / abs(max_drawdown)
        else:
            calmar_ratio = np.inf if annualized_return > 0 else 0.0

        # 8. Distribution Tails (Skewness and Kurtosis)
        skewness = returns.skew() if len(returns) > 2 else 0.0
        kurtosis = returns.kurtosis() if len(returns) > 3 else 0.0

        return {
            "total_return_pct": total_return * 100,
            "annualized_return_pct": annualized_return * 100,
            "max_drawdown_pct": max_drawdown * 100,
            "annualized_volatility_pct": annualized_volatility * 100,
            "sharpe_ratio": sharpe_ratio,
            "sortino_ratio": sortino_ratio,
            "calmar_ratio": calmar_ratio,
            "skewness": skewness,
            "kurtosis": kurtosis,
        }

    @staticmethod
    def calculate_trade_metrics(
        trades: Union[List[dict], pd.DataFrame],
    ) -> Dict[str, float]:
        """
        Calculates performance analytics from a ledger of closed trades.
        Requires 'net_pnl' column/key. Optional: 'opened_at', 'closed_at'.
        """
        if isinstance(trades, list):
            if not trades:
                return _empty_trade_metrics()
            df = pd.DataFrame(trades)
        else:
            df = trades

        if df is None or df.empty or "net_pnl" not in df.columns:
            return _empty_trade_metrics()

        total_trades = len(df)

        winners = df[df["net_pnl"] > 0]
        losers = df[df["net_pnl"] <= 0]

        num_winners = len(winners)
        num_losers = len(losers)

        # 1. Win Rate
        win_rate = num_winners / total_trades

        # 2. Average Win / Loss
        avg_win = winners["net_pnl"].mean() if num_winners > 0 else 0.0
        avg_loss = losers["net_pnl"].mean() if num_losers > 0 else 0.0

        # 3. Profit Factor
        gross_profit = winners["net_pnl"].sum() if num_winners > 0 else 0.0
        gross_loss = abs(losers["net_pnl"].sum()) if num_losers > 0 else 0.0

        if gross_loss > 0:
            profit_factor = gross_profit / gross_loss
        else:
            profit_factor = np.inf if gross_profit > 0 else 0.0

        # 4. Expectancy
        # Expectancy = (Win Rate * Avg Win) + (Loss Rate * Avg Loss)
        # Note: avg_loss is already negative in our dataframe representation
        expectancy = (win_rate * avg_win) + ((1 - win_rate) * avg_loss)

        # 5. Average Trade Duration
        avg_duration_minutes = 0.0
        if "opened_at" in df.columns and "closed_at" in df.columns:
            try:
                # Convert ISO strings to datetime
                opened = pd.to_datetime(df["opened_at"])
                closed = pd.to_datetime(df["closed_at"])
                durations = (closed - opened).dt.total_seconds() / 60.0
                avg_duration_minutes = durations.mean()
            except Exception:
                pass  # Fallback to 0.0 if parsing fails

        return {
            "total_trades": total_trades,
            "win_rate_pct": win_rate * 100,
            "profit_factor": profit_factor,
            "expectancy": expectancy,
            "average_win": avg_win,
            "average_loss": avg_loss,
            "average_duration_minutes": avg_duration_minutes,
        }

    @staticmethod
    def calculate_full_tearsheet(
        equity_series: pd.Series,
        trades: Union[List[dict], pd.DataFrame],
        initial_equity: float = 10000.0,
    ) -> dict:
        """
        Combines equity metrics, trade metrics, and Monte Carlo probabilistic risk statistics into a single flat dictionary.
        """
        equity_metrics = PerformanceMetrics.calculate_equity_metrics(equity_series)
        trade_metrics = PerformanceMetrics.calculate_trade_metrics(trades)

        from analysis.risk_metrics import RiskMetrics

        # Use equity returns for the Monte Carlo bootstrap
        mc_stats = RiskMetrics._empty_mc_stats()
        if isinstance(equity_series, pd.Series) and len(equity_series) > 1:
            returns = equity_series.pct_change().dropna()
            if not returns.empty:
                curves = RiskMetrics.run_monte_carlo_simulation(
                    returns.values, initial_equity=initial_equity
                )
                mc_stats = RiskMetrics.calculate_monte_carlo_statistics(
                    curves, initial_equity=initial_equity
                )

        # Merge dictionaries
        return {**equity_metrics, **trade_metrics, **mc_stats}


def _empty_equity_metrics() -> dict:
    return {
        "total_return_pct": 0.0,
        "annualized_return_pct": 0.0,
        "max_drawdown_pct": 0.0,
        "annualized_volatility_pct": 0.0,
        "sharpe_ratio": 0.0,
        "sortino_ratio": 0.0,
        "calmar_ratio": 0.0,
        "skewness": 0.0,
        "kurtosis": 0.0,
    }


def _empty_trade_metrics() -> dict:
    return {
        "total_trades": 0,
        "win_rate_pct": 0.0,
        "profit_factor": 0.0,
        "expectancy": 0.0,
        "average_win": 0.0,
        "average_loss": 0.0,
        "average_duration_minutes": 0.0,
    }
