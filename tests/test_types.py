"""Tests for common/types.py — enums and dataclasses."""
from common.types import (
    Side, SignalAction, Regime, OrderType,
    Signal, VolumeProfile, GridLevel, GridState, DcaLevel,
)


class TestEnums:
    def test_side_values(self):
        assert Side.LONG == "LONG"
        assert Side.SHORT == "SHORT"

    def test_signal_action_values(self):
        assert SignalAction.ENTER_LONG == "ENTER_LONG"
        assert SignalAction.EXIT_SHORT == "EXIT_SHORT"
        assert SignalAction.DCA_ADD == "DCA_ADD"
        assert SignalAction.GRID_PLACE == "GRID_PLACE"

    def test_regime_values(self):
        assert Regime.TREND == "trend"
        assert Regime.RANGE == "range"

    def test_enum_string_comparison(self):
        """Enums inherit from str, so should compare to raw strings."""
        assert Side.LONG == "LONG"
        assert SignalAction.HOLD == "HOLD"


class TestSignal:
    def test_signal_defaults(self):
        sig = Signal(symbol="BTC/USDT", action=SignalAction.HOLD)
        assert sig.symbol == "BTC/USDT"
        assert sig.side is None
        assert sig.price is None
        assert sig.amount is None
        assert sig.stop_loss is None
        assert sig.take_profit is None
        assert sig.strategy == ""
        assert sig.confidence == 0.0
        assert isinstance(sig.meta, dict)

    def test_signal_with_values(self, signal_long):
        assert signal_long.price == 60000.0
        assert signal_long.stop_loss == 58000.0
        assert signal_long.take_profit == 64000.0
        assert signal_long.amount == 0.01


class TestVolumeProfile:
    def test_volume_profile_construction(self):
        vp = VolumeProfile(poc=100.0, vah=110.0, val=90.0)
        assert vp.poc == 100.0
        assert vp.vah == 110.0
        assert vp.val == 90.0
        assert vp.vah > vp.val


class TestGridLevel:
    def test_grid_level_defaults(self):
        gl = GridLevel(price=50000.0, side="buy", amount=0.01)
        assert gl.price == 50000.0
        assert gl.filled == False
