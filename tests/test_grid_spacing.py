import pytest
from strategy.neutral_grid_strategy import NeutralGridStrategy
from common.types import VolumeProfile
from config.config_loader import Config


class MockConfig:
    GRID_ATR_MULTIPLIER = 0.5
    GRID_MAX_LEVELS = 20
    GRID_LEVELS = 5


@pytest.fixture
def strategy():
    return NeutralGridStrategy(MockConfig())


def test_generate_grid_levels_normal(strategy):
    vp = VolumeProfile(poc=100.0, vah=110.0, val=90.0)
    market_state = {"atr": 2.0, "volatility_regime": "MEDIUM"}

    # k = 0.5, ATR = 2.0 -> Spacing = 1.0
    # max_distance = 100 * 0.025 = 2.5
    # bounds = int(2.5 / 1.0) = 2
    levels = strategy.generate_grid_levels("BTC", vp, 1000.0, market_state)

    assert len(levels) == 4

    buys = [l for l in levels if l.side == "buy"]
    sells = [l for l in levels if l.side == "sell"]

    assert len(buys) == 2
    assert len(sells) == 2

    # Check spacing
    assert min([l.price for l in buys]) == 98.0
    assert max([l.price for l in buys]) == 99.0

    assert min([l.price for l in sells]) == 101.0
    assert max([l.price for l in sells]) == 102.0


def test_generate_grid_levels_high_vol(strategy):
    vp = VolumeProfile(poc=100.0, vah=110.0, val=90.0)
    market_state = {"atr": 2.0, "volatility_regime": "HIGH"}

    # k = 0.5 * 1.5 = 0.75
    # Spacing = 0.75 * 2.0 = 1.5
    # bounds = int(2.5 / 1.5) = 1
    levels = strategy.generate_grid_levels("BTC", vp, 1000.0, market_state)

    assert len(levels) == 2


def test_generate_grid_levels_low_vol(strategy):
    vp = VolumeProfile(poc=100.0, vah=110.0, val=90.0)
    market_state = {"atr": 2.0, "volatility_regime": "LOW"}

    # k = 0.5 * 0.8 = 0.4
    # Spacing = 0.4 * 2.0 = 0.8
    # bounds = int(2.5 / 0.8) = 3
    levels = strategy.generate_grid_levels("BTC", vp, 1000.0, market_state)

    assert len(levels) == 6
