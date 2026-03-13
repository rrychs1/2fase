import json
import pandas as pd
import numpy as np
import logging
from typing import Optional, Union, Dict
from analysis.performance_metrics import PerformanceMetrics

logger = logging.getLogger(__name__)

class StrategyEvaluator:
    """
    Framework to evaluate strategy performance from historical trade logs.
    Ingests JSONL files, synthesizes an equity curve, computes statistics via PerformanceMetrics, and generates reports.
    """
    
    @staticmethod
    def load_trades_from_jsonl(filepath: str) -> pd.DataFrame:
        """
        Loads trades from a JSON Lines (JSONL) file into a pandas DataFrame.
        Each line must be a valid JSON object representing a single closed trade.
        """
        trades = []
        try:
            with open(filepath, 'r') as f:
                for line in f:
                    if line.strip():
                        trades.append(json.loads(line))
            df = pd.DataFrame(trades)
            
            # Attempt to convert timestamps if they exist
            if 'closed_at' in df.columns:
                df['closed_at'] = pd.to_datetime(df['closed_at'])
                df.sort_values('closed_at', inplace=True)
                df.reset_index(drop=True, inplace=True)
                
            return df
        except Exception as e:
            logger.error(f"Failed to load trades from {filepath}: {e}")
            return pd.DataFrame()
            
    @staticmethod
    def generate_synthetic_equity_curve(trades_df: pd.DataFrame, initial_balance: float = 10000.0) -> pd.Series:
        """
        Synthesizes an equity curve time-series from a ledger of trades.
        Requires a 'net_pnl' column.
        """
        if trades_df.empty or 'net_pnl' not in trades_df.columns:
            return pd.Series([initial_balance])
            
        # Create an array of cumulative PnL
        cumulative_pnl = trades_df['net_pnl'].cumsum()
        
        # Build equity curve: start with initial balance, then step through each trade
        equity_values = [initial_balance] + (initial_balance + cumulative_pnl).tolist()
        
        # Try to use 'closed_at' as the index if possible
        if 'closed_at' in trades_df.columns:
            # Ensure it is a datetime series
            trades_df['closed_at'] = pd.to_datetime(trades_df['closed_at'])
            
            # We need one extra timestamp for the initial balance. We can just use the first trade minus 1 second
            first_ts = trades_df['closed_at'].iloc[0]
            start_ts = first_ts - pd.Timedelta(seconds=1)
            index = [start_ts] + trades_df['closed_at'].tolist()
            return pd.Series(equity_values, index=index)
        else:
            return pd.Series(equity_values)
            
    @staticmethod
    def evaluate_strategy(trades_df: pd.DataFrame, initial_balance: float = 10000.0) -> Dict[str, float]:
        """
        Runs the full performance and risk analytical tearsheet against the trades.
        """
        equity_curve = StrategyEvaluator.generate_synthetic_equity_curve(trades_df, initial_balance)
        
        tearsheet = PerformanceMetrics.calculate_full_tearsheet(
            equity_series=equity_curve,
            trades=trades_df,
            initial_equity=initial_balance
        )
        
        # Inject Statistical Overfitting Tests if returns data is sufficient
        from analysis.statistical_tests import StatisticalOverfittingTests
        if len(equity_curve) > 5:
            returns = equity_curve.pct_change().dropna().values
            dsr = StatisticalOverfittingTests.calculate_deflated_sharpe_ratio(returns, n_trials=100, var_trials=0.5)
            spa = StatisticalOverfittingTests.hansens_spa(returns, n_bootstraps=5000, block_size=5)
            boot_p = StatisticalOverfittingTests.calculate_p_value_bootstrap(returns, n_bootstraps=5000, block_size=5)
            
            risk_score = StatisticalOverfittingTests.calculate_overfitting_risk_score(
                dsr['psr_p_value'], spa['spa_p_value'], boot_p
            )
            
            tearsheet['dsr_p_value'] = dsr['psr_p_value']
            tearsheet['spa_p_value'] = spa['spa_p_value']
            tearsheet['boot_p_value'] = boot_p
            tearsheet['overfitting_risk_score'] = risk_score
        else:
            tearsheet['dsr_p_value'] = 1.0
            tearsheet['spa_p_value'] = 1.0
            tearsheet['boot_p_value'] = 1.0
            tearsheet['overfitting_risk_score'] = 100.0
            
        return tearsheet
        
    @staticmethod
    def generate_markdown_report(tearsheet: dict, strategy_name: str = "Strategy", filepath: str = None) -> str:
        """
        Formats a tearsheet dictionary into a structured Markdown document.
        Optionally saves it to disk.
        """
        md = f"# Strategy Performance Report: {strategy_name}\n\n"
        
        md += "## Executive Summary\n"
        md += f"- **Net Return:** {tearsheet.get('total_return_pct', 0.0):.2f}%\n"
        md += f"- **Annualized Return:** {tearsheet.get('annualized_return_pct', 0.0):.2f}%\n"
        md += f"- **Maximum Drawdown:** {tearsheet.get('max_drawdown_pct', 0.0):.2f}%\n"
        md += f"- **Total Trades:** {tearsheet.get('total_trades', 0)}\n\n"
        
        md += "## Risk-Adjusted Metrics\n"
        md += f"- **Sharpe Ratio:** {tearsheet.get('sharpe_ratio', 0.0):.4f}\n"
        md += f"- **Sortino Ratio:** {tearsheet.get('sortino_ratio', 0.0):.4f}\n"
        md += f"- **Calmar Ratio:** {tearsheet.get('calmar_ratio', 0.0):.4f}\n\n"
        
        md += "## Trade Ledger Statistics\n"
        md += f"- **Win Rate:** {tearsheet.get('win_rate_pct', 0.0):.2f}%\n"
        md += f"- **Profit Factor:** {tearsheet.get('profit_factor', 0.0):.2f}\n"
        md += f"- **Trade Expectancy (USD):** ${tearsheet.get('expectancy', 0.0):.2f}\n"
        md += f"- **Average Win:** ${tearsheet.get('average_win', 0.0):.2f}\n"
        md += f"- **Average Loss:** ${tearsheet.get('average_loss', 0.0):.2f}\n"
        md += f"- **Average Duration:** {tearsheet.get('average_duration_minutes', 0.0):.1f} mins\n\n"
        
        md += "## Monte Carlo Stress Testing\n"
        md += "> Based on 10,000 bootstrap simulations of the empirical trade distribution.\n\n"
        md += f"- **Expected Median Return:** {tearsheet.get('mc_median_return_pct', 0.0):.2f}%\n"
        md += f"- **Expected 95% Worst Drawdown:** {tearsheet.get('mc_95_percentile_drawdown_pct', 0.0):.2f}%\n"
        md += f"- **Probability of Ruin (-50% equity):** {tearsheet.get('mc_probability_of_ruin_pct', 0.0):.2f}%\n\n"
        
        md += "## Financial Econometrics Overfitting Tests\n"
        md += f"- **Deflated Sharpe (PSR) p-value:** {tearsheet.get('dsr_p_value', 1.0):.4f}\n"
        md += f"- **Hansen's SPA p-value:** {tearsheet.get('spa_p_value', 1.0):.4f}\n"
        md += f"- **Block Bootstrap p-value:** {tearsheet.get('boot_p_value', 1.0):.4f}\n"
        md += f"- **OVERFITTING RISK SCORE:** {tearsheet.get('overfitting_risk_score', 100.0):.1f}%\n"
        
        if filepath:
            try:
                with open(filepath, 'w', encoding='utf-8') as f:
                    f.write(md)
                logger.info(f"Markdown report saved to {filepath}")
            except Exception as e:
                logger.error(f"Failed to write markdown report to {filepath}: {e}")
                
        return md

    @staticmethod
    def export_to_csv(tearsheet: dict, filepath: str) -> bool:
        """
        Dumps the flat tearsheet dictionary into a 2-column CSV file.
        """
        try:
            df = pd.DataFrame(list(tearsheet.items()), columns=['Metric', 'Value'])
            df.to_csv(filepath, index=False)
            logger.info(f"Metrics CSV exported to {filepath}")
            return True
        except Exception as e:
            logger.error(f"Failed to export CSV to {filepath}: {e}")
            return False
