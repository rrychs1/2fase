"""
Backtest runner — CLI entry point.

Usage:
    python run_backtest.py
    python run_backtest.py --symbol ETH/USDT --start 2025-06-01 --end 2026-01-01 --tf 1h
    python run_backtest.py --symbol BTC/USDT --balance 50000
"""
import argparse
import logging
import sys

from backtesting.data_loader import load_historical
from backtesting.backtest_engine import BacktestEngine
from backtesting.metrics import print_metrics
from backtesting.report import generate_report

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(description="Run a backtest on historical data")
    parser.add_argument("--symbol", default="BTC/USDT", help="Trading pair (default: BTC/USDT)")
    parser.add_argument("--start", default="2025-08-01", help="Start date YYYY-MM-DD (default: 2025-08-01)")
    parser.add_argument("--end", default="2026-02-01", help="End date YYYY-MM-DD (default: 2026-02-01)")
    parser.add_argument("--tf", default="4h", help="Timeframe (default: 4h)")
    parser.add_argument("--balance", type=float, default=10000.0, help="Initial balance (default: 10000)")
    parser.add_argument("--maker-fee", type=float, default=0.0004, help="Maker fee rate (default: 0.04%%)")
    parser.add_argument("--taker-fee", type=float, default=0.0006, help="Taker fee rate (default: 0.06%%)")
    parser.add_argument("--lookback", type=int, default=250, help="Lookback candles for indicators (default: 250)")
    parser.add_argument("--no-report", action="store_true", help="Skip HTML report generation")

    args = parser.parse_args()

    print(f"\n{'=' * 60}")
    print(f"  BACKTESTING ENGINE")
    print(f"{'=' * 60}")
    print(f"  Symbol:    {args.symbol}")
    print(f"  Period:    {args.start} -> {args.end}")
    print(f"  Timeframe: {args.tf}")
    print(f"  Balance:   ${args.balance:,.2f}")
    print(f"  Fees:      {args.maker_fee * 100:.2f}% maker / {args.taker_fee * 100:.2f}% taker")
    print(f"  Lookback:  {args.lookback} candles")
    print(f"{'=' * 60}\n")

    # 1. Load historical data
    logger.info("Step 1/3: Loading historical data...")
    df = load_historical(args.symbol, args.tf, args.start, args.end)
    if df.empty:
        logger.error("No data loaded. Exiting.")
        sys.exit(1)
    logger.info(f"Loaded {len(df)} candles from {df['timestamp'].iloc[0]} to {df['timestamp'].iloc[-1]}")

    # 2. Run backtest
    logger.info("Step 2/3: Running backtest...")
    engine = BacktestEngine(
        symbol=args.symbol,
        timeframe=args.tf,
        initial_balance=args.balance,
        maker_fee=args.maker_fee,
        taker_fee=args.taker_fee,
        lookback=args.lookback,
    )
    metrics = engine.run(df)

    # 3. Print results
    print_metrics(metrics)

    # 4. Generate HTML report
    if not args.no_report:
        logger.info("Step 3/3: Generating HTML report...")
        report_path = generate_report(
            metrics=metrics,
            equity_curve=engine.broker.equity_curve,
            trades=engine.broker.trades,
            symbol=args.symbol,
            timeframe=args.tf,
            start_date=args.start,
            end_date=args.end,
            initial_balance=args.balance,
        )
        print(f"\n📊 HTML Report: {report_path}")
    else:
        logger.info("Skipping HTML report (--no-report flag)")

    print("\n[+] Backtest complete!\n")


if __name__ == "__main__":
    main()
