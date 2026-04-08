import pytest
from execution.portfolio_engine import Portfolio


def test_portfolio_initialization():
    portfolio = Portfolio(initial_balance=1000.0)
    assert portfolio.balance == 1000.0
    assert portfolio.calculate_equity() == 1000.0
    assert len(portfolio.positions) == 0


def test_simulate_execution_slippage():
    # 0.02% slippage
    portfolio = Portfolio(slippage_rate=0.0002)

    # LONG gets a higher price (worse)
    exec_price, _ = portfolio.simulate_execution(100.0, "LONG", is_maker=False)
    assert exec_price == 100.02

    # SHORT gets a lower price (worse)
    exec_price, _ = portfolio.simulate_execution(100.0, "SHORT", is_maker=False)
    assert exec_price == 99.98

    # Limit orders (maker) have no slippage
    exec_price, _ = portfolio.simulate_execution(100.0, "LONG", is_maker=True)
    assert exec_price == 100.0


def test_open_position_long():
    portfolio = Portfolio(initial_balance=1000.0, fee_rate=0.001, slippage_rate=0.0)

    pos = portfolio.open_position("BTC/USDT", "LONG", 50000.0, 0.01)

    assert pos["symbol"] == "BTC/USDT"
    assert pos["side"] == "LONG"
    assert pos["amount"] == 0.01

    # Notional: 50000 * 0.01 = 500
    # Fee: 500 * 0.001 = 0.5
    # Balance should be: 1000 - 0.5 = 999.5
    assert portfolio.balance == 999.5
    assert pos["fees_paid"] == 0.5


def test_dca_average_price():
    portfolio = Portfolio(initial_balance=1000.0, fee_rate=0.0, slippage_rate=0.0)

    portfolio.open_position("ETH/USDT", "LONG", 2000.0, 0.1)
    portfolio.open_position("ETH/USDT", "LONG", 1000.0, 0.1)

    pos = portfolio.positions["ETH/USDT"]
    assert pos["amount"] == 0.2
    assert pos["average_price"] == 1500.0


def test_update_price_and_equity():
    portfolio = Portfolio(initial_balance=1000.0, fee_rate=0.0, slippage_rate=0.0)
    portfolio.open_position("BTC/USDT", "LONG", 50000.0, 0.01)

    portfolio.update_price("BTC/USDT", 60000.0)

    # PnL = (60000 - 50000) * 0.01 = +100
    assert portfolio.positions["BTC/USDT"]["unrealized_pnl"] == 100.0
    assert portfolio.calculate_equity() == 1100.0

    # Drop below entry
    portfolio.update_price("BTC/USDT", 40000.0)
    assert portfolio.positions["BTC/USDT"]["unrealized_pnl"] == -100.0
    assert portfolio.calculate_equity() == 900.0


def test_close_position_short():
    portfolio = Portfolio(initial_balance=1000.0, fee_rate=0.001, slippage_rate=0.0)

    # Open SHORT at 50,000
    portfolio.open_position("BTC/USDT", "SHORT", 50000.0, 0.01)

    # Close at 40,000 (Win)
    record = portfolio.close_position("BTC/USDT", 40000.0)

    # Gross Pnl = (50000 - 40000) * 0.01 = +100
    # Entry fee: 50,000 * 0.01 * 0.001 = 0.5
    # Exit fee: 40,000 * 0.01 * 0.001 = 0.4
    # Total fee = 0.9
    # Net Pnl = 99.1

    assert record["gross_pnl"] == 100.0
    assert record["net_pnl"] == 99.1
    assert record["total_fees"] == 0.9
    assert (
        portfolio.balance == 1000.0 + 99.1
    )  # Balance updates accurately based on net impact
    assert len(portfolio.positions) == 0


def test_invalid_hedging():
    portfolio = Portfolio()
    portfolio.open_position("BTC/USDT", "LONG", 50000.0, 0.01)
    with pytest.raises(ValueError, match="Hedging not supported"):
        portfolio.open_position("BTC/USDT", "SHORT", 50000.0, 0.01)


def test_partial_position_close():
    portfolio = Portfolio(initial_balance=1000.0, fee_rate=0.001, slippage_rate=0.0)

    # 1. Open 0.1 BTC at 50k (Notional 5000, Fee 5) -> Balance 995
    portfolio.open_position("BTC/USDT", "LONG", 50000.0, 0.1)
    assert portfolio.balance == 995.0

    # 2. Close 0.04 BTC at 60k (Gain: (60-50)*0.04 = +400)
    # Proportional Entry Fee: (5 / 0.1) * 0.04 = 2
    # Exit Fee: (60000 * 0.04 * 0.001) = 2.4
    # Total Fee for this portion: 4.4
    # Net PnL: 400 - 4.4 = 395.6
    # Balance should be: 995 - 2.4 (exit fee) + 400 (gross profit) = 1392.6

    record = portfolio.close_position("BTC/USDT", 60000.0, amount=0.04)

    assert record["is_partial"] is True
    assert record["amount"] == 0.04
    assert record["net_pnl"] == 395.6
    assert portfolio.balance == 1392.6

    # 3. Check remaining position
    pos = portfolio.positions["BTC/USDT"]
    assert pos["amount"] == pytest.approx(0.06)  # 0.1 - 0.04
    assert pos["fees_paid"] == pytest.approx(
        3.0
    )  # 5.0 - 2.0 (proportional entry fee removed)


def test_multi_asset_equity():
    portfolio = Portfolio(initial_balance=10000.0, fee_rate=0.0, slippage_rate=0.0)

    # Open BTC (1.0 @ 50k) and ETH (10 @ 2k)
    portfolio.open_position("BTC/USDT", "LONG", 50000.0, 1.0)
    portfolio.open_position("ETH/USDT", "LONG", 2000.0, 10.0)

    # Price moves: BTC to 55k (+5000), ETH to 1.8k (-2000)
    portfolio.update_price("BTC/USDT", 55000.0)
    portfolio.update_price("ETH/USDT", 1800.0)

    # Total Unrealized: 5000 - 2000 = 3000
    assert portfolio.calculate_equity() == 13000.0


def test_negative_pnl_closing():
    portfolio = Portfolio(initial_balance=1000.0, fee_rate=0.0, slippage_rate=0.0)
    portfolio.open_position("BTC/USDT", "LONG", 50000.0, 0.01)

    # Price drops to 40k. Loss = (40-50)*0.01 = -100
    record = portfolio.close_position("BTC/USDT", 40000.0)

    assert record["net_pnl"] == -100.0
    assert portfolio.balance == 900.0


def test_rapid_dca_and_partial_exits():
    portfolio = Portfolio(initial_balance=1000.0, fee_rate=0.0, slippage_rate=0.0)

    # DCA sequence
    portfolio.open_position("BTC/USDT", "LONG", 100.0, 1.0)
    portfolio.open_position("BTC/USDT", "LONG", 50.0, 1.0)
    # Avg: 75, Amount 2.0

    # Partial Exit at 150
    portfolio.close_position("BTC/USDT", 150.0, amount=1.0)
    # Gain: (150-75)*1.0 = +75. Balance: 1075. Remaining: 1.0 at 75.

    assert portfolio.balance == 1075.0
    assert portfolio.positions["BTC/USDT"]["amount"] == 1.0

    # Final close at 200
    portfolio.close_position("BTC/USDT", 200.0)
    # Gain: (200-75)*1.0 = +125. Balance: 1075 + 125 = 1200.

    assert portfolio.balance == 1200.0


def test_close_more_than_available_safety():
    portfolio = Portfolio(initial_balance=1000.0, fee_rate=0.0, slippage_rate=0.0)
    portfolio.open_position("BTC/USDT", "LONG", 100.0, 1.0)

    # Attempt to close 5.0 when only 1.0 exists
    record = portfolio.close_position("BTC/USDT", 110.0, amount=5.0)

    assert record["amount"] == 1.0  # Should be capped at max available
    assert len(portfolio.positions) == 0
