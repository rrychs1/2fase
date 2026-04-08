import abc


class MarketDataProvider(abc.ABC):
    @abc.abstractmethod
    async def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int):
        pass

    @abc.abstractmethod
    async def get_current_price(self, symbol: str):
        pass


class ExecutionProvider(abc.ABC):
    @abc.abstractmethod
    async def execute_order_safe(self, signal, order_type: str, params: dict = None):
        pass

    @abc.abstractmethod
    async def fetch_open_orders(self, symbol: str):
        pass

    @abc.abstractmethod
    async def cancel_all_orders(self, symbol: str):
        pass

    @abc.abstractmethod
    async def close_all_positions(self):
        pass


class PortfolioProvider(abc.ABC):
    @abc.abstractmethod
    async def get_account_pnl(self):
        pass

    @abc.abstractmethod
    async def get_equity(self):
        pass

    @abc.abstractmethod
    async def fetch_positions(self):
        pass

    @abc.abstractmethod
    async def get_position(self, symbol: str):
        pass
