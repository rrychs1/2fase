import logging
from core.interfaces import MarketDataProvider

logger = logging.getLogger(__name__)


class LiveMarketDataProvider(MarketDataProvider):
    """Real-World Market Interface connecting directly to the ExchangeClient logic."""

    def __init__(self, exchange):
        self.exchange = exchange

    async def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int):
        return await self.exchange.fetch_ohlcv(symbol, timeframe, limit)

    async def get_current_price(self, symbol: str):
        try:
            ticker = await self.exchange.fetch_ticker(symbol)
            return ticker.get("last")
        except Exception:
            return None
