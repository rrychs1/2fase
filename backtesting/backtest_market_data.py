import logging
import pandas as pd
from core.interfaces import MarketDataProvider

logger = logging.getLogger(__name__)

class BacktestMarketDataProvider(MarketDataProvider):
    """Simulated Market Interface returning historical DataFrame blocks seamlessly."""
    def __init__(self, data: pd.DataFrame):
        self.data = data
        self.current_idx = 0

    async def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int):
        # Natively returns the slice up to current_idx
        start = max(0, self.current_idx - limit + 1)
        return self.data.iloc[start:self.current_idx + 1]

    async def get_current_price(self, symbol: str):
        if self.current_idx >= len(self.data):
            return self.data.iloc[-1]['close']
        return self.data.iloc[self.current_idx]['close']
