import pandas as pd
import ta.trend as trend_i
import ta.momentum as momentum_i
import ta.volatility as volatility_i


def add_standard_indicators(df: pd.DataFrame) -> pd.DataFrame:
    # Defensas por si el DF está vacío o le faltan columnas
    required_cols = {"open", "high", "low", "close"}
    if (
        not isinstance(df, pd.DataFrame)
        or len(df) == 0
        or not required_cols.issubset(df.columns)
    ):
        return df

    close = df["close"]
    high = df["high"]
    low = df["low"]

    # EMAs
    df["EMA_fast"] = trend_i.EMAIndicator(close=close, window=50).ema_indicator()
    df["EMA_slow"] = trend_i.EMAIndicator(close=close, window=200).ema_indicator()

    # MACD
    macd_obj = trend_i.MACD(close=close)
    df["MACD"] = macd_obj.macd()
    df["MACD_signal"] = macd_obj.macd_signal()
    df["MACD_hist"] = macd_obj.macd_diff()

    # RSI
    df["RSI"] = momentum_i.RSIIndicator(close=close, window=14).rsi()

    # ATR
    df["ATR"] = volatility_i.AverageTrueRange(
        high=high, low=low, close=close, window=14
    ).average_true_range()

    # ADX
    adx_obj = trend_i.ADXIndicator(high=high, low=low, close=close, window=14)
    df["ADX"] = adx_obj.adx()

    # Bollinger Bands
    bb_obj = volatility_i.BollingerBands(close=close, window=20, window_dev=2)
    df["BB_lower"] = bb_obj.bollinger_lband()
    df["BB_upper"] = bb_obj.bollinger_hband()
    # Bandwidth: (upper - lower) / close  — mismo criterio que antes
    df["BB_width"] = bb_obj.bollinger_wband()

    return df
