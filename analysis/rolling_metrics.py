import pandas as pd
import numpy as np
from typing import Union


class RollingPerformanceMetrics:
    """
    Computes dynamic rolling statistics (Sharpe, Drawdown, Profit Factor)
    using efficient vectorized pandas operations.
    """

    @staticmethod
    def calculate_rolling_metrics(
        trades_df: pd.DataFrame,
        window: Union[int, str] = 100,
        min_periods: int = 5,
        annualize_factor: int = 365,
    ) -> pd.DataFrame:
        """
        Calculates all rolling metrics given a window size (integer trade count or string time offset like '30d').
        """
        if trades_df.empty or "net_pnl" not in trades_df.columns:
            return pd.DataFrame()

        df = trades_df.copy()

        # Ensure timestamp index exists if using string offset
        if isinstance(window, str):
            # Normalize frequency string (e.g., '30d' -> '30D')
            if window.endswith("d"):
                window = window.replace("d", "D")

            if "exit_time" in df.columns:
                df["exit_time"] = pd.to_datetime(df["exit_time"])
                df.set_index("exit_time", inplace=True)
                df.sort_index(inplace=True)
            else:
                raise ValueError(
                    "String window requires 'exit_time' column for time index."
                )

        rolling = df.rolling(window=window, min_periods=min_periods)

        metrics = pd.DataFrame(index=df.index)

        # 1. Total return & Volatility (PnL terms)
        metrics["cumulative_pnl"] = df["net_pnl"].cumsum()
        metrics["rolling_pnl_sum"] = rolling["net_pnl"].sum()

        # Assuming net_pnl is already a % return for standard math. If it's absolute, Vol/Sharpe is nominal.
        metrics["rolling_volatility"] = rolling["net_pnl"].std()

        # 2. Rolling Sharpe Ratio (Annualized)
        raw_sharpe = rolling["net_pnl"].mean() / metrics["rolling_volatility"]
        # Replace inf with nan
        raw_sharpe.replace([np.inf, -np.inf], np.nan, inplace=True)
        metrics["rolling_sharpe"] = raw_sharpe * np.sqrt(annualize_factor)

        # 3. Rolling Win Rate
        is_win = (df["net_pnl"] > 0).astype(int)
        metrics["rolling_win_rate"] = is_win.rolling(
            window=window, min_periods=min_periods
        ).mean()

        # 4. Rolling Profit Factor
        pos_pnl = df["net_pnl"].where(df["net_pnl"] > 0, 0)
        neg_pnl = df["net_pnl"].where(df["net_pnl"] < 0, 0).abs()

        roll_gross_profit = pos_pnl.rolling(
            window=window, min_periods=min_periods
        ).sum()
        roll_gross_loss = neg_pnl.rolling(window=window, min_periods=min_periods).sum()

        pf = roll_gross_profit / roll_gross_loss
        pf.replace([np.inf, -np.inf], np.nan, inplace=True)
        metrics["rolling_profit_factor"] = pf

        # 5. Rolling Expectancy
        # Expectancy = (Win Rate * Avg Win) - (Loss Rate * Avg Loss)
        # Using simple mean is faster if separated
        avg_win = (
            df["net_pnl"][df["net_pnl"] > 0]
            .rolling(window=window, min_periods=min_periods)
            .mean()
        )
        avg_loss = (
            df["net_pnl"][df["net_pnl"] < 0]
            .abs()
            .rolling(window=window, min_periods=min_periods)
            .mean()
        )

        # Fill missing avg win/loss with 0 for formula
        avg_win = avg_win.reindex(df.index).ffill().fillna(0)
        avg_loss = avg_loss.reindex(df.index).ffill().fillna(0)

        win_rate = metrics["rolling_win_rate"]
        loss_rate = 1.0 - win_rate
        metrics["rolling_expectancy"] = (win_rate * avg_win) - (loss_rate * avg_loss)

        # 6. Correct Cumulative Drawdown
        # Drawdown is calculated from the global maximum reached up to that point
        metrics["cummax_pnl"] = metrics["cumulative_pnl"].cummax()
        metrics["current_drawdown_pnl"] = (
            metrics["cummax_pnl"] - metrics["cumulative_pnl"]
        )

        # Optional: As percentage if initial equity is known. Here we just track absolute DD if PnL is absolute.

        return metrics
