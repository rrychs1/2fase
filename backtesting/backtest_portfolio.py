import logging
from core.interfaces import PortfolioProvider

logger = logging.getLogger(__name__)

class BacktestPortfolioProvider(PortfolioProvider):
    """Mocks realistic equity state loops mapping perfectly into the native Shadow configurations."""
    def __init__(self, shadow_executor):
        self.shadow = shadow_executor

    async def get_account_pnl(self):
        return self.shadow.get_unrealized_pnl()

    async def get_equity(self):
        return self.shadow.get_equity()

    async def fetch_positions(self):
        return self.shadow.positions

    async def get_position(self, symbol: str):
        return self.shadow.positions.get(symbol, {})
