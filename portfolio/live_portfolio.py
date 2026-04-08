import logging
from core.interfaces import PortfolioProvider

logger = logging.getLogger(__name__)


class LivePortfolioProvider(PortfolioProvider):
    """Extracts genuine Portfolio states accurately from native Exchange configurations."""

    def __init__(self, execution_router):
        self.router = execution_router

    async def get_account_pnl(self):
        state = await self.router.get_portfolio_state()
        return state.get("unrealized_pnl", 0.0)

    async def get_equity(self):
        state = await self.router.get_portfolio_state()
        return state.get("equity", 0.0)

    async def fetch_positions(self):
        state = await self.router.get_portfolio_state()
        return state.get("positions", {})

    async def get_position(self, symbol: str):
        state = await self.router.get_portfolio_state()
        positions = state.get("positions", {})
        return positions.get(symbol, {})
