import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from execution.execution_router import ExecutionRouter
from common.types import Side, Signal, SignalAction


@pytest.fixture
def mock_exchange():
    exchange = MagicMock()
    exchange.fetch_order_book = AsyncMock()
    return exchange


@pytest.fixture
def router(mock_exchange, config):
    return ExecutionRouter(mock_exchange, config)


@pytest.fixture
def base_signal():
    return Signal(
        symbol="BTC/USDT",
        action=SignalAction.ENTER_LONG,
        side=Side.LONG,
        price=60000.0,
        amount=1.0,  # Target 1 BTC
        stop_loss=58000.0,
        take_profit=65000.0,
        strategy="test",
    )


class TestOrderBookLiquidityConsumption:
    @pytest.mark.asyncio
    async def test_long_consumes_asks(self, router, mock_exchange, base_signal):
        # OB with plenty of bid depth but shallow ask depth
        mock_exchange.fetch_order_book.return_value = {
            "bids": [[59900.0, 10.0], [59800.0, 10.0]],
            "asks": [[60100.0, 0.1], [60200.0, 0.1]],  # 0.2 total ask depth
        }

        # Long signal should look at asks
        sized_amount, _ = await router.calculate_liquidity_sizing(
            "BTC/USDT", base_signal
        )

        # Effective depth = 0.2 * (1 - 0.2 haircut) = 0.16
        # Max allowed = 0.16 * 0.1 ratio = 0.016
        assert sized_amount < 0.02
        assert sized_amount > 0

    @pytest.mark.asyncio
    async def test_short_consumes_bids(self, router, mock_exchange, base_signal):
        base_signal.side = Side.SHORT
        base_signal.action = SignalAction.ENTER_SHORT

        # OB with shallow bid depth
        mock_exchange.fetch_order_book.return_value = {
            "bids": [[59900.0, 0.1], [59800.0, 0.1]],  # 0.2 total bid depth
            "asks": [[60100.0, 10.0], [60200.0, 10.0]],
        }

        sized_amount, _ = await router.calculate_liquidity_sizing(
            "BTC/USDT", base_signal
        )
        assert sized_amount < 0.02


class TestDepthBoundaryAndHaircuts:
    @pytest.mark.asyncio
    async def test_one_percent_limit_ignored(self, router, mock_exchange, base_signal):
        # Mid price = 60000. 1% limit is 60600.
        mock_exchange.fetch_order_book.return_value = {
            "bids": [[59900, 10]],
            "asks": [
                [60100, 1.0],  # Inside 1%
                [60500, 1.0],  # Inside 1%
                [60700, 10.0],  # OUTSIDE 1% (ignored)
            ],
        }

        sized_amount, _ = await router.calculate_liquidity_sizing(
            "BTC/USDT", base_signal
        )
        # Expected depth_vol = 2.0.
        # Haircut 20% -> 1.6. Ratio 10% -> 0.16.
        assert abs(sized_amount - 0.16) < 1e-6


class TestVWAPSlippageScaling:
    @pytest.mark.asyncio
    async def test_vwap_scaling_down(self, router, mock_exchange, base_signal, config):
        config.MAX_SLIPPAGE_PCT = 0.001  # 0.1% for strict test
        # Mid price = 100. Spreading depth wide to force slippage.
        mock_exchange.fetch_order_book.return_value = {
            "bids": [[99, 100]],
            "asks": [[101, 1.0], [105, 1.0], [110, 10.0]],
        }
        base_signal.price = 100.0
        base_signal.amount = 1.5  # We want 1.5.
        # Total depth in 1% (up to 101) is 1.0.
        # effective = 1.0 * 0.8 = 0.8. Max allowed = 0.08.
        # But let's check VWAP logic if we bypass depth for a second to test scaling.

        with patch.object(
            router.config, "MAX_ORDER_DEPTH_RATIO", 1.0
        ):  # Ignore depth ratio to test VWAP
            # Mid = 101+99 / 2 = 100
            # Target 1.5. Consumes 1.0 at 101, 0.5 at 105.
            # VWAP = (1.0*101 + 0.5*105) / 1.5 = (101 + 52.5) / 1.5 = 153.5 / 1.5 = 102.33
            # Slippage = (102.33 - 100) / 100 = 2.33%
            # Max Slip = 0.1%. Scaling factor = 0.001 / 0.0233 = 0.0429
            # Final amount = 1.5 * 0.0429 = 0.064
            sized, _ = await router.calculate_liquidity_sizing("BTC/USDT", base_signal)
            assert sized < 0.1


class TestSpreadAndEdgeCases:
    @pytest.mark.asyncio
    async def test_max_spread_blocks_trade(
        self, router, mock_exchange, base_signal, config
    ):
        config.MAX_SPREAD_PCT = 0.01  # 1%
        # 2% spread
        mock_exchange.fetch_order_book.return_value = {
            "bids": [[59000, 10]],
            "asks": [[60200, 10]],
        }

        sized_amount, _ = await router.calculate_liquidity_sizing(
            "BTC/USDT", base_signal
        )
        assert sized_amount == 0.0

    @pytest.mark.asyncio
    async def test_empty_book_safe_handling(self, router, mock_exchange, base_signal):
        mock_exchange.fetch_order_book.return_value = None
        sized_amount, _ = await router.calculate_liquidity_sizing(
            "BTC/USDT", base_signal
        )
        # Should return original amount as fallback or log warning (code says return amount)
        assert sized_amount == base_signal.amount

    @pytest.mark.asyncio
    async def test_zero_depth_blocks(self, router, mock_exchange, base_signal):
        # OB exists but ask depth is 0
        mock_exchange.fetch_order_book.return_value = {
            "bids": [[59900, 10]],
            "asks": [],
        }
        sized_amount, _ = await router.calculate_liquidity_sizing(
            "BTC/USDT", base_signal
        )
        assert sized_amount == 0.0
