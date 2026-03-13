import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from execution.execution_router import ExecutionRouter
from common.types import Side, Signal, SignalAction

@pytest.fixture
def mock_exchange():
    exchange = MagicMock()
    exchange.fetch_order_book = AsyncMock(return_value={
        'bids': [[59900, 10]],
        'asks': [[60100, 10]]
    })
    exchange.fetch_balance = AsyncMock(return_value={'total': {'USDT': 10000.0}})
    return exchange

@pytest.fixture
def signal_long():
    return Signal(
        symbol="BTC/USDT",
        action=SignalAction.ENTER_LONG,
        side=Side.LONG,
        price=60000.0,
        amount=0.01,
        stop_loss=58000.0,
        take_profit=62000.0,
        strategy="test"
    )

class TestExecutionRouterRouting:
    @pytest.mark.asyncio
    async def test_shadow_routing_isolation(self, config, mock_exchange, signal_long):
        config.EXECUTION_MODE = 'SHADOW'
        router = ExecutionRouter(mock_exchange, config)
        
        # Mock the internal executors
        router.shadow_executor = MagicMock()
        router.paper_manager = MagicMock()
        router.live_engine = MagicMock()
        
        # Execute
        await router.execute_signal(signal_long)
        
        # Verify
        router.shadow_executor.execute_signal.assert_called_once()
        router.paper_manager.execute_signal.assert_not_called()
        router.live_engine.place_order.assert_not_called()
        # Verify liquidity sizing was called (it's part of the route)
        mock_exchange.fetch_order_book.assert_called()

    @pytest.mark.asyncio
    async def test_paper_routing_isolation(self, config, mock_exchange, signal_long):
        config.EXECUTION_MODE = 'PAPER'
        router = ExecutionRouter(mock_exchange, config)
        
        router.shadow_executor = MagicMock()
        router.paper_manager = MagicMock()
        router.live_engine = MagicMock()
        
        await router.execute_signal(signal_long)
        
        router.paper_manager.execute_signal.assert_called_once()
        router.shadow_executor.execute_signal.assert_not_called()
        router.live_engine.place_order.assert_not_called()

    @pytest.mark.asyncio
    async def test_live_routing_calls_engine(self, config, mock_exchange, signal_long):
        config.EXECUTION_MODE = 'LIVE'
        router = ExecutionRouter(mock_exchange, config)
        
        # Live mode uses the live_engine (ExecutionEngine)
        router.live_engine = MagicMock()
        router.live_engine.place_order = AsyncMock(return_value={'id': '123'})
        
        await router.execute_signal(signal_long)
        
        # Should call market order for entry, then SL and TP
        assert router.live_engine.place_order.call_count >= 1
        # First call should be the market buy
        router.live_engine.place_order.assert_any_call("BTC/USDT", "long", "market", 0.01)

    @pytest.mark.asyncio
    async def test_signal_integrity_preserved(self, config, mock_exchange, signal_long):
        config.EXECUTION_MODE = 'PAPER'
        router = ExecutionRouter(mock_exchange, config)
        
        original_price = signal_long.price
        original_sl = signal_long.stop_loss
        
        await router.execute_signal(signal_long)
        
        assert signal_long.price == original_price
        assert signal_long.stop_loss == original_sl
        # Amount might change due to liquidity sizing, which is intended behavior
        # But other fields must stay same.

    @pytest.mark.asyncio
    async def test_emergency_close_all_routing(self, config, mock_exchange):
        # Test Shadow
        config.EXECUTION_MODE = 'SHADOW'
        router = ExecutionRouter(mock_exchange, config)
        router.shadow_executor = MagicMock()
        await router.close_all_positions()
        router.shadow_executor.close_all_positions.assert_called_once()
        
        # Test Live
        config.EXECUTION_MODE = 'LIVE'
        router = ExecutionRouter(mock_exchange, config)
        router.live_engine = MagicMock()
        router.live_engine.close_all_positions = AsyncMock()
        await router.close_all_positions()
        router.live_engine.close_all_positions.assert_called_once()

    @pytest.mark.asyncio
    async def test_liquidity_scaling_applies_to_signal(self, config, mock_exchange, signal_long):
        config.EXECUTION_MODE = 'PAPER'
        router = ExecutionRouter(mock_exchange, config)
        
        # Tiny liquidity in OB
        mock_exchange.fetch_order_book.return_value = {
            'bids': [[59900, 10]],
            'asks': [[60100, 0.001]] # Very low liquidity
        }
        
        signal_long.amount = 1.0 # Want 1 BTC
        await router.execute_signal(signal_long)
        
        # Verify signal.amount was reduced
        assert signal_long.amount < 1.0
        assert signal_long.amount > 0
