import pytest
import asyncio
from common.types import Signal, SignalAction, Side
from risk.core_risk_engine import CoreRiskEngine


class MockConfig:
    def __init__(self):
        self.RISK_MAX_OPEN_POSITIONS = 5
        self.RISK_MAX_POSITION_PER_SYMBOL = 0.10  # 10%
        self.MAX_TOTAL_EXPOSURE = 0.50  # 50%
        self.RISK_MAX_DRAWDOWN = 0.20  # 20%
        self.RISK_MAX_DAILY_LOSS = 0.05  # 5%


@pytest.fixture
def base_state():
    return {
        "balance": 10000.0,
        "equity": 10000.0,
        "high_water_mark": 10000.0,
        "start_of_day_balance": 10000.0,
        "positions": {},
    }


@pytest.fixture
def risk_engine(base_state):
    config = MockConfig()
    # We pass a lambda so we can dynamically mutate the base_state in tests
    return CoreRiskEngine(config, lambda: base_state)


def create_signal(
    symbol: str,
    amount: float,
    price: float,
    action: SignalAction = SignalAction.ENTER_LONG,
) -> Signal:
    import datetime

    return Signal(
        symbol=symbol,
        action=action,
        side=Side.LONG if "LONG" in action.name else Side.SHORT,
        price=price,
        amount=amount,
        strategy="TestMock",
        timestamp=datetime.datetime.now(datetime.timezone.utc),
    )


class TestCoreRiskEngineUnit:

    # ------------------------------------------------------------------------- #
    # CASE A: Max drawdown breach
    # ------------------------------------------------------------------------- #
    def test_max_drawdown_breach(self, risk_engine, base_state):
        # Initial HWM is 10,000. Limit is 20%. Equity drops to 7,900 (21% DD).
        base_state["equity"] = 7900.0
        base_state["high_water_mark"] = 10000.0

        assert risk_engine.should_shutdown() is True

    def test_max_drawdown_safe(self, risk_engine, base_state):
        base_state["equity"] = 8100.0  # 19% DD
        base_state["high_water_mark"] = 10000.0
        base_state["start_of_day_balance"] = 8100.0  # Prevent daily loss trigger
        assert risk_engine.should_shutdown() is False

    # ------------------------------------------------------------------------- #
    # CASE B: Daily loss breach
    # ------------------------------------------------------------------------- #
    def test_daily_loss_breach(self, risk_engine, base_state):
        # SOD is 10,000. Limit is 5%. Equity drops to 9,400 (6% daily loss).
        base_state["equity"] = 9400.0
        base_state["start_of_day_balance"] = 10000.0

        assert risk_engine.should_shutdown() is True

    def test_daily_loss_safe(self, risk_engine, base_state):
        base_state["equity"] = 9600.0  # 4% loss
        assert risk_engine.should_shutdown() is False

    # ------------------------------------------------------------------------- #
    # CASE C: Oversized order (Max Position Per Symbol)
    # ------------------------------------------------------------------------- #
    def test_oversized_order_blocked(self, risk_engine):
        # Max pos per symbol is 10% of 10k = 1000 USDT.
        # Try to buy 1500 USDT worth of BTC
        ord_oversize = create_signal(
            "BTC/USDT", amount=150.0, price=10.0
        )  # 1500 Notional
        assert risk_engine.validate_order(ord_oversize) is False

    def test_normal_order_allowed(self, risk_engine):
        # Try to buy 900 USDT worth
        ord_normal = create_signal("BTC/USDT", amount=90.0, price=10.0)  # 900 Notional
        assert risk_engine.validate_order(ord_normal) is True

    # ------------------------------------------------------------------------- #
    # CASE D: Total exposure breach
    # ------------------------------------------------------------------------- #
    def test_total_exposure_breach(self, risk_engine, base_state):
        # Max total is 50% = 5000 USDT.
        # Add positions already active = 4500 USDT exposure
        base_state["positions"] = {
            "ETH/USDT": {
                "amount": 20.0,
                "entry_price": 100.0,
                "is_active": True,
            },  # 2000 USDT
            "SOL/USDT": {
                "amount": 50.0,
                "entry_price": 50.0,
                "is_active": True,
            },  # 2500 USDT
        }

        # We try to add a new position of 600 USDT.
        # Total would be 4500 + 600 = 5100 > 5000 USDT. Should be blocked.
        ord_breach = create_signal("ADA/USDT", amount=60.0, price=10.0)
        assert risk_engine.validate_order(ord_breach) is False

    def test_total_exposure_safe(self, risk_engine, base_state):
        base_state["positions"] = {
            "ETH/USDT": {
                "amount": 20.0,
                "entry_price": 100.0,
                "is_active": True,
            },  # 2000 USDT
            "SOL/USDT": {
                "amount": 50.0,
                "entry_price": 50.0,
                "is_active": True,
            },  # 2500 USDT
        }

        # We try to add a new position of 400 USDT.
        # Total would be 4500 + 400 = 4900 < 5000 USDT. Should be allowed.
        ord_safe = create_signal("ADA/USDT", amount=40.0, price=10.0)
        assert risk_engine.validate_order(ord_safe) is True

    # ------------------------------------------------------------------------- #
    # CASE E: Cumulative small orders exceeding limits
    # ------------------------------------------------------------------------- #
    def test_cumulative_small_orders_symbol_limit(self, risk_engine, base_state):
        # Symbol limit is 1000 USDT.
        # Existing position is 800 USDT.
        base_state["positions"] = {
            "BTC/USDT": {"amount": 80.0, "entry_price": 10.0, "is_active": True}
        }

        # We add 2 orders sequentially: 150 USDT, then 100 USDT.
        ord_1 = create_signal("BTC/USDT", amount=15.0, price=10.0)
        # First one should be allowed (800 + 150 = 950 <= 1000)
        assert risk_engine.validate_order(ord_1) is True

        # Simulating state updating after execution:
        base_state["positions"]["BTC/USDT"]["amount"] += 15.0

        ord_2 = create_signal("BTC/USDT", amount=10.0, price=10.0)
        # Second one blocked (950 + 100 = 1050 > 1000)
        assert risk_engine.validate_order(ord_2) is False

    # ------------------------------------------------------------------------- #
    # CASE F: Max Open Positions
    # ------------------------------------------------------------------------- #
    def test_max_open_positions_breach(self, risk_engine, base_state):
        # Limit is 5. We have 5 open.
        for i in range(5):
            base_state["positions"][f"SYM{i}/USDT"] = {
                "amount": 10.0,
                "entry_price": 10.0,
                "is_active": True,
            }

        ord_new = create_signal("SYM6/USDT", amount=10.0, price=10.0)
        assert risk_engine.validate_order(ord_new) is False

        # But adding to an EXISTING position is allowed
        ord_update = create_signal("SYM0/USDT", amount=10.0, price=10.0)
        assert (
            risk_engine.validate_order(ord_update) is True
        )  # As long as notional passes!


class TestCoreRiskEngineStress:
    # ------------------------------------------------------------------------- #
    # FALSIFICATION: Splitting Orders (Rapid Fire)
    # ------------------------------------------------------------------------- #
    @pytest.mark.asyncio
    async def test_rapid_fire_order_splitting(self):
        """
        Simulates an attacker/bot malfunction generating 100 lightning-fast micro-sized orders
        attempting to bypass the 1000 USDT symbol cap cumulatively.
        """
        config = MockConfig()

        # We define a state dict container
        state = {
            "balance": 10000.0,
            "equity": 10000.0,
            "positions": {
                "BTC/USDT": {"amount": 0.0, "entry_price": 10.0, "is_active": True}
            },
        }

        # We need the risk engine to dynamically read this state pointer
        engine = CoreRiskEngine(config, lambda: state)

        # The bot attempts to spam 100 micro orders of 20 USDT each (Total=2000 USDT).
        # We simulate the exact sequential behavior of validate -> execute -> update state.
        approved_orders = 0
        blocked_orders = 0

        for _ in range(100):
            sig = create_signal("BTC/USDT", amount=2.0, price=10.0)  # 20 Notional

            # Validation Step
            if engine.validate_order(sig):
                approved_orders += 1
                # Execution happens instantly conceptually: state updates
                state["positions"]["BTC/USDT"]["amount"] += sig.amount
            else:
                blocked_orders += 1

        # Final Notional is target_amount * entry_price
        final_notional = state["positions"]["BTC/USDT"]["amount"] * 10.0

        # Ensure the hard stop of 1000 USDT is mathematically enforced unconditionally
        assert final_notional <= 1000.0
        assert approved_orders == 50  # 50 * 20 = 1000
        assert blocked_orders == 50  # Remaining 50 blocked

    def test_negative_equity_block_all(self, risk_engine, base_state):
        base_state["equity"] = -500.0

        assert risk_engine.should_shutdown() is True

        ord_new = create_signal("SYM/USDT", amount=10.0, price=10.0)
        assert risk_engine.validate_order(ord_new) is False
