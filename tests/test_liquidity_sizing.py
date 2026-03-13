import pytest
import asyncio
from common.types import Signal, SignalAction, Side
from config.config_loader import Config
from execution.execution_router import ExecutionRouter

class MockConfig(Config):
    MAX_ORDER_DEPTH_RATIO = 0.10
    LIQUIDITY_HAIRCUT = 0.20
    MAX_SPREAD_PCT = 0.005 # 0.5%
    MAX_SLIPPAGE_PCT = 0.002 # 0.2%
    EXECUTION_MODE = 'PAPER'

class MockExchange:
    def __init__(self):
        self.mock_ob = None
        self.fetch_calls = 0

    async def fetch_order_book(self, symbol, limit):
        self.fetch_calls += 1
        return self.mock_ob

@pytest.fixture
def router():
    exchange = MockExchange()
    r = ExecutionRouter(exchange, MockConfig())
    return r

@pytest.mark.asyncio
async def test_liquidity_sizing_normal_pass(router):
    # Mid = 100. 1% is 101.
    router.exchange.mock_ob = {
        "bids": [[99.9, 1000], [99.0, 1000]],
        "asks": [[100.1, 500], [100.5, 500]] # 1000 vol under 101
    }
    # Depth = 1000
    # Haircut 20% -> 800 effective depth
    # Max ratio 10% -> 80 max allowed
    
    signal = Signal(symbol="BTC", action=SignalAction.ENTER_LONG, side=Side.LONG, price=100.1, amount=50.0)
    
    allowed = await router.calculate_liquidity_sizing("BTC", signal)
    assert allowed == 50.0 # Full amount allowed

@pytest.mark.asyncio
async def test_liquidity_sizing_depth_limit(router):
    # Mid = 100
    router.exchange.mock_ob = {
        "bids": [[99.9, 1000], [99.0, 1000]],
        "asks": [[100.1, 500], [100.5, 500]] # Total Ask Volume in 1% = 1000
    }
    # Max allowed after haircut (20%) and ratio (10%) = 80
    
    signal = Signal(symbol="BTC", action=SignalAction.ENTER_LONG, side=Side.LONG, price=100.1, amount=200.0)
    
    allowed = await router.calculate_liquidity_sizing("BTC", signal)
    # Target amount is capped at max depth limit (80)
    # Then checks VWAP.
    # 80 units eaten at 100.1. VWAP = 100.1. Mid = 100.
    # slippage = 0.1 / 100 = 0.1%. Max slip = 0.2%. No VWAP reduction.
    assert allowed == 80.0

@pytest.mark.asyncio
async def test_liquidity_sizing_vwap_slippage(router):
    # Mid = 100. 
    # High VWAP scenario.
    router.exchange.mock_ob = {
        "bids": [[99.9, 1000]],
        "asks": [[100.1, 10], [100.4, 90]] # 100 total vol
    }
    # Max allowed depth: 100 * 0.8 * 0.1 = 8 units permitted by depth limits
    # The signal wants 8 units. 
    # Let's walk the book for 8 units: entirely consumed at 100.1.
    # VWAP = 100.1. Slippage = 0.1%. (passes)
    
    # Force larger depth to test VWAP bottleneck exclusively:
    router.exchange.mock_ob = {
        "bids": [[99.9, 10000]],
        "asks": [[100.1, 1], [100.5, 999]] # 1000 total vol in 1%
    }
    # Max allowed depth = 1000 * 0.8 * 0.1 = 80
    signal = Signal(symbol="BTC", action=SignalAction.ENTER_LONG, side=Side.LONG, price=100.1, amount=80.0)
    
    # Walking 80 units:
    # 1 unit @ 100.1
    # 79 units @ 100.5
    # VWAP = (1*100.1 + 79*100.5) / 80 = 7949.6 / 80 = 99.37... wait 100.495
    # Slippage = (100.495 - 100) / 100 = ~0.495%.
    # Max slip = 0.2%.
    # Ratio = 0.2 / 0.495 = ~0.404.
    # Final amount = 80 * 0.404 = 32.32
    
    allowed = await router.calculate_liquidity_sizing("BTC", signal)
    
    assert allowed < 80.0
    assert abs(allowed - 32.32) < 0.1

@pytest.mark.asyncio
async def test_liquidity_sizing_spread_protection(router):
    # Wide spread: bid 90, ask 110. Spread = 20 / 90 = 22%.
    router.exchange.mock_ob = {
        "bids": [[90.0, 1000]],
        "asks": [[110.0, 1000]]
    }
    
    signal = Signal(symbol="BTC", action=SignalAction.ENTER_LONG, side=Side.LONG, price=110.0, amount=50.0)
    allowed = await router.calculate_liquidity_sizing("BTC", signal)
    
    # Blocked completely.
    assert allowed == 0.0

@pytest.mark.asyncio
async def test_liquidity_sizing_empty_ob(router):
    router.exchange.mock_ob = {"bids": [], "asks": []}
    
    signal = Signal(symbol="BTC", action=SignalAction.ENTER_LONG, side=Side.LONG, price=100.0, amount=50.0)
    allowed = await router.calculate_liquidity_sizing("BTC", signal)
    
    # Blocked for safety when book is empty.
    assert allowed == 0.0
