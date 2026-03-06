import logging
import pandas as pd
from exchange.exchange_client import ExchangeClient

logger = logging.getLogger(__name__)

class DataEngine:
    def __init__(self, exchange_client: ExchangeClient):
        self.exchange = exchange_client
        self.data = {} # Stores DataFrames per symbol and timeframe

    async def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int = 500) -> pd.DataFrame:
        """Fetches OHLCV with retry-backoff and basic validation."""
        import asyncio
        if not symbol or "/" not in symbol:
            logger.error(f"[DataEngine] Invalid symbol: {symbol}")
            return None
            
        max_retries = 3
        for attempt in range(max_retries):
            try:
                ohlcv = await self.exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
                if ohlcv is not None and len(ohlcv) > 0:
                    df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
                    self.data[(symbol, timeframe)] = df
                    return df
                else:
                    logger.warning(f"[DataEngine] Empty data for {symbol} (Attempt {attempt+1}/{max_retries})")
            except Exception as e:
                wait = (attempt + 1) * 2
                logger.warning(f"[DataEngine] Error fetching {symbol}: {e}. Retrying in {wait}s...")
                await asyncio.sleep(wait)
                
        logger.error(f"[DataEngine] Failed to fetch data for {symbol} after {max_retries} attempts.")
        return None

    async def update_ohlcv(self, symbol: str, timeframe: str) -> pd.DataFrame:
        # Incremental update logic would go here
        return await self.fetch_ohlcv(symbol, timeframe, limit=100)
