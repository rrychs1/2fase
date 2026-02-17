import pandas as pd
from exchange.exchange_client import ExchangeClient

class DataEngine:
    def __init__(self, exchange_client: ExchangeClient):
        self.exchange = exchange_client
        self.data = {} # Stores DataFrames per symbol and timeframe

    async def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int = 500) -> pd.DataFrame:
        ohlcv = await self.exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        self.data[(symbol, timeframe)] = df
        return df

    async def update_ohlcv(self, symbol: str, timeframe: str) -> pd.DataFrame:
        # Incremental update logic would go here
        return await self.fetch_ohlcv(symbol, timeframe, limit=100)
