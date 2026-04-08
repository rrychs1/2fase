import pytest
from risk.risk_manager import RiskManager
from common.types import Signal, SignalAction, Side
from config.config_loader import Config


class MockConfig(Config):
    MAX_INVENTORY_RATIO = 0.15
    MAX_TOTAL_EXPOSURE = 0.50
    LEVERAGE = 3
    MAX_RISK_PER_TRADE = 0.05
    DAILY_LOSS_LIMIT = 0.10


@pytest.fixture
def risk_manager():
    rm = RiskManager(MockConfig())
    # Mock reference equity
    rm.reference_equity = 10000.0
    return rm


def test_enforce_inventory_limits_empty_portfolio(risk_manager):
    # Empty portfolio -> 10000 equity
    # Max per asset: 1500
    # Max total: 5000
    current_positions = {}
    signal = Signal(
        symbol="BTC/USDT",
        action=SignalAction.ENTER_LONG,
        side=Side.LONG,
        price=50000.0,
        amount=0.02,
    )
    # Notional: 50000 * 0.02 = 1000
    # Should be fully approved
    allowed = risk_manager.enforce_inventory_limits(
        "BTC/USDT", signal, current_positions
    )
    assert allowed == 0.02


def test_enforce_inventory_limits_symbol_reduction(risk_manager):
    # Current BTC/USDT position notional = 1200
    # Max allowed for BTC = 1500
    # Remaining = 300
    current_positions = {"BTC/USDT": {"amount": 0.024, "average_price": 50000.0}}

    # New signal wants 0.01 (Notional = 500)
    signal = Signal(
        symbol="BTC/USDT",
        action=SignalAction.ENTER_LONG,
        side=Side.LONG,
        price=50000.0,
        amount=0.01,
    )

    # Only 300 allowed, so amount should be bounded to 300 / 50000 = 0.006
    allowed = risk_manager.enforce_inventory_limits(
        "BTC/USDT", signal, current_positions
    )
    assert allowed == 0.006


def test_enforce_inventory_limits_global_reduction(risk_manager):
    # Current total notional = 4800 (Max allowed globally = 5000)
    # New symbol ETH/USDT wants to buy 1 ETH at 300 (Notional 300)
    current_positions = {
        "BTC/USDT": {"amount": 0.096, "average_price": 50000.0}  # 4800
    }

    signal = Signal(
        symbol="ETH/USDT",
        action=SignalAction.ENTER_LONG,
        side=Side.LONG,
        price=300.0,
        amount=1.0,
    )

    # Remaining globally = 200
    # Max for ETH = 1500
    # Minimum remaining = 200. Allowed amount = 200 / 300 = 0.6666...
    allowed = risk_manager.enforce_inventory_limits(
        "ETH/USDT", signal, current_positions
    )
    assert abs(allowed - (200.0 / 300.0)) < 1e-6


def test_enforce_inventory_limits_blocked(risk_manager):
    # Current BTC/USDT already at limit 1500
    current_positions = {"BTC/USDT": {"amount": 0.03, "average_price": 50000.0}}  # 1500

    signal = Signal(
        symbol="BTC/USDT",
        action=SignalAction.ENTER_LONG,
        side=Side.LONG,
        price=50000.0,
        amount=0.01,
    )

    # Should block and return 0
    allowed = risk_manager.enforce_inventory_limits(
        "BTC/USDT", signal, current_positions
    )
    assert allowed == 0.0


def test_enforce_inventory_limits_exit(risk_manager):
    # Exits should not be blocked by inventory logic
    current_positions = {"BTC/USDT": {"amount": 0.03, "average_price": 50000.0}}  # 1500
    signal = Signal(
        symbol="BTC/USDT",
        action=SignalAction.EXIT_LONG,
        side=Side.LONG,
        price=50000.0,
        amount=0.03,
    )

    allowed = risk_manager.enforce_inventory_limits(
        "BTC/USDT", signal, current_positions
    )
    assert allowed == 0.03
