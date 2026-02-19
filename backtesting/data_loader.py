"""
Historical OHLCV data loader for backtesting.
Downloads from Binance via CCXT (public API, no keys needed) and caches to CSV.
"""
import os
import ccxt
import pandas as pd
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")


def _ensure_data_dir():
    os.makedirs(DATA_DIR, exist_ok=True)


def _cache_filename(symbol: str, timeframe: str, start: str, end: str) -> str:
    """Generate deterministic cache filename."""
    safe_symbol = symbol.replace("/", "-")
    return os.path.join(DATA_DIR, f"{safe_symbol}_{timeframe}_{start}_{end}.csv")


def load_historical(
    symbol: str,
    timeframe: str = "4h",
    start_date: str = "2025-08-01",
    end_date: str = "2026-02-01",
) -> pd.DataFrame:
    """
    Load historical OHLCV data. Fetches from Binance if not cached.

    Args:
        symbol: Trading pair, e.g. "BTC/USDT"
        timeframe: Candle timeframe, e.g. "1h", "4h", "1d"
        start_date: Start date string "YYYY-MM-DD"
        end_date: End date string "YYYY-MM-DD"

    Returns:
        DataFrame with columns: timestamp, open, high, low, close, volume
    """
    _ensure_data_dir()

    cache_file = _cache_filename(symbol, timeframe, start_date, end_date)

    # Return cached data if available
    if os.path.exists(cache_file):
        logger.info(f"Loading cached data from {cache_file}")
        df = pd.read_csv(cache_file, parse_dates=["timestamp"])
        logger.info(f"Loaded {len(df)} candles from cache")
        return df

    # Fetch from Binance
    logger.info(f"Downloading {symbol} {timeframe} from {start_date} to {end_date}...")

    exchange = ccxt.binance({"enableRateLimit": True})

    start_ms = int(datetime.strptime(start_date, "%Y-%m-%d").timestamp() * 1000)
    end_ms = int(datetime.strptime(end_date, "%Y-%m-%d").timestamp() * 1000)

    all_candles = []
    since = start_ms
    batch_size = 1000

    while since < end_ms:
        try:
            candles = exchange.fetch_ohlcv(
                symbol, timeframe, since=since, limit=batch_size
            )
        except Exception as e:
            logger.error(f"Error fetching OHLCV: {e}")
            break

        if not candles:
            break

        all_candles.extend(candles)
        last_ts = candles[-1][0]

        # Prevent infinite loop if exchange returns same timestamp
        if last_ts <= since:
            break
        since = last_ts + 1

        logger.info(
            f"  Fetched {len(all_candles)} candles so far "
            f"(last: {datetime.fromtimestamp(last_ts / 1000).strftime('%Y-%m-%d %H:%M')})"
        )

        # Stop if we passed end_date
        if last_ts >= end_ms:
            break

    if not all_candles:
        logger.error("No candles fetched!")
        return pd.DataFrame()

    df = pd.DataFrame(all_candles, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")

    # Filter to exact range
    end_dt = datetime.strptime(end_date, "%Y-%m-%d")
    df = df[df["timestamp"] < end_dt].reset_index(drop=True)

    # Remove duplicates
    df = df.drop_duplicates(subset=["timestamp"]).reset_index(drop=True)

    # Save cache
    df.to_csv(cache_file, index=False)
    logger.info(f"Saved {len(df)} candles to {cache_file}")

    return df
