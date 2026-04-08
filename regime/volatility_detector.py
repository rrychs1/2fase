import pandas as pd
import numpy as np
import logging

logger = logging.getLogger(__name__)


class VolatilityRegimeDetector:
    """
    Detects market volatility regimes (LOW, MEDIUM, HIGH)
    using Average True Range (ATR) and Price Percentage Volatility.
    Designed to be efficient for real-time dataframe analysis.
    """

    def __init__(
        self,
        atr_period: int = 14,
        low_threshold: float = 1.5,
        high_threshold: float = 3.5,
    ):
        """
        :param atr_period: Lookback period for ATR and STD.
        :param low_threshold: Volatility % below this is LOW.
        :param high_threshold: Volatility % above this is HIGH. Between low and high is MEDIUM.
        """
        self.atr_period = atr_period
        self.low_threshold = low_threshold
        self.high_threshold = high_threshold

    def calculate_atr(self, df: pd.DataFrame) -> pd.Series:
        """
        Calculates the Average True Range (ATR) efficiently over the dataframe.
        """
        if len(df) < self.atr_period:
            return pd.Series(np.nan, index=df.index)

        # True Range: max(high-low, abs(high-prev_close), abs(low-prev_close))
        high_low = df["high"] - df["low"]

        # Shift close to get previous close
        prev_close = df["close"].shift(1)

        high_pclose = (df["high"] - prev_close).abs()
        low_pclose = (df["low"] - prev_close).abs()

        # Combine taking the element-wise maximum
        tr = pd.concat([high_low, high_pclose, low_pclose], axis=1).max(axis=1)

        # ATR is the rolling mean of TR
        atr = tr.rolling(window=self.atr_period).mean()
        return atr

    def calculate_volatility_percent(self, df: pd.DataFrame) -> pd.Series:
        """
        Calculates the Volatility Percentage.
        Uses the rolling standard deviation of daily returns annualized,
        or more simply, the standard deviation of returns over the period.
        Here we use rolling standard deviation of percentage returns * 100 for percentage scale.
        """
        if len(df) < self.atr_period:
            return pd.Series(np.nan, index=df.index)

        returns = df["close"].pct_change()
        # Multiply by 100 to get a whole number percentage (e.g., 2.5%)
        # Normalize by sqrt of period (optional, here we rely on the raw standard deviation over the period)
        vol_pct = returns.rolling(window=self.atr_period).std() * 100
        return vol_pct

    def detect_regime(self, df: pd.DataFrame) -> str:
        """
        Analyzes the DataFrame and returns the current volatility regime:
        LOW, MEDIUM, or HIGH.
        Requires columns: 'high', 'low', 'close'
        """
        if len(df) < self.atr_period + 1:
            logger.warning(
                "Not enough data to determine volatility regime. Defaulting to MEDIUM."
            )
            return "MEDIUM"

        vol_pct_series = self.calculate_volatility_percent(df)

        current_vol_pct = vol_pct_series.iloc[-1]

        if pd.isna(current_vol_pct):
            return "MEDIUM"

        if current_vol_pct < self.low_threshold:
            regime = "LOW"
        elif current_vol_pct > self.high_threshold:
            regime = "HIGH"
        else:
            regime = "MEDIUM"

        logger.debug(f"Volatility %: {current_vol_pct:.2f} -> Regime: {regime}")
        return regime
