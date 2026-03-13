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
    market_state = {
        'atr': 2.0,
        'volatility_regime': 'MEDIUM'
    }
    
    # k = 0.5, ATR = 2.0 -> Spacing = 1.0
    # buy levels: (100 - 90) / 1.0 = 10
    # sell levels: (110 - 100) / 1.0 = 10
    levels = strategy.generate_grid_levels("BTC", vp, 1000.0, market_state)
    
    assert len(levels) == 20
    
    buys = [l for l in levels if l.side == 'buy']
    sells = [l for l in levels if l.side == 'sell']
    
    assert len(buys) == 10
    assert len(sells) == 10
    
    # Check spacing
    assert min([l.price for l in buys]) == 90.0
    assert max([l.price for l in buys]) == 99.0
    
    assert min([l.price for l in sells]) == 101.0
    assert max([l.price for l in sells]) == 110.0

def test_generate_grid_levels_high_vol(strategy):
    vp = VolumeProfile(poc=100.0, vah=110.0, val=90.0)
    market_state = {
        'atr': 2.0,
        'volatility_regime': 'HIGH'
    }
    
    # k = 0.5 * 1.5 = 0.75
    # Spacing = 0.75 * 2.0 = 1.5
    # levels per side: 10 / 1.5 = 6 (int division)
    levels = strategy.generate_grid_levels("BTC", vp, 1000.0, market_state)
    
    assert len(levels) == 12

def test_generate_grid_levels_low_vol(strategy):
    vp = VolumeProfile(poc=100.0, vah=110.0, val=90.0)
    market_state = {
        'atr': 2.0,
        'volatility_regime': 'LOW'
    }
    
    # k = 0.5 * 0.8 = 0.4
    # Spacing = 0.4 * 2.0 = 0.8
    # levels per side: 10 / 0.8 = 12
    # Total = 24.
    # Exceeds GRID_MAX_LEVELS (20). Should scale spacing so total levels = 20.
    # scale factor = 24 / 20 = 1.2
    # new spacing = 0.8 * 1.2 = 0.96
    # expected levels per side: int(10 / 0.96) = 10 -> total 20!
    levels = strategy.generate_grid_levels("BTC", vp, 1000.0, market_state)
    
    assert len(levels) == 20
