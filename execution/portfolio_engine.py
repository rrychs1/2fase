import logging
from typing import Dict, List, Optional
from datetime import datetime, UTC
from logging_monitoring.metrics_server import bot_total_trades, bot_winning_trades, bot_realized_pnl

logger = logging.getLogger(__name__)

class Portfolio:
    """
    Virtual Portfolio Engine for Paper and Shadow Trading.
    Tracks balances, open positions, PnL, and simulated fees/slippage.
    """
    def __init__(self, initial_balance: float = 10000.0, fee_rate: float = 0.0004, slippage_rate: float = 0.0002):
        self.initial_balance = initial_balance
        self.balance = initial_balance
        self.fee_rate = fee_rate
        self.slippage_rate = slippage_rate
        
        # State
        self.positions: Dict[str, dict] = {}
        self.history: List[dict] = []
        self.current_prices: Dict[str, float] = {}
        self.total_realized_pnl = 0.0

    def simulate_execution(self, price: float, side: str, is_maker: bool = False) -> tuple[float, float]:
        """
        Calculates execution price with slippage and the associated fee amount.
        Returns: (executed_price, fee_percentage_rate)
        """
        # Apply Slippage (worse price for the trader)
        # Long entry = buy = higher price, Short entry = sell = lower price
        # is_maker ignores slippage since limit orders don't skip price
        if not is_maker:
            slippage = price * self.slippage_rate
            executed_price = price + slippage if side.upper() == "LONG" else price - slippage
        else:
            executed_price = price

        return executed_price, self.fee_rate

    def open_position(self, symbol: str, side: str, price: float, amount: float, is_maker: bool = False) -> dict:
        """
        Opens or adds to a position. 
        """
        side = side.upper()
        if side not in ["LONG", "SHORT"]:
            raise ValueError(f"Invalid side: {side}")
            
        executed_price, fee_pct = self.simulate_execution(price, side, is_maker)
        
        notional = executed_price * amount
        fee = notional * fee_pct
        
        # Deduct fee from balance
        self.balance -= fee

        if symbol in self.positions:
            pos = self.positions[symbol]
            # Average down / DCA logic
            if pos["side"] != side:
                raise ValueError(f"Hedging not supported in simple portfolio. Active side: {pos['side']}")
            
            old_notional = pos["average_price"] * pos["amount"]
            new_notional = old_notional + notional
            new_amount = pos["amount"] + amount
            
            pos["average_price"] = new_notional / new_amount
            pos["amount"] = new_amount
            pos["fees_paid"] += fee
            
            logger.debug(f"Added to {symbol} position. New Avg: {pos['average_price']}, Amount: {pos['amount']}")
        else:
            self.positions[symbol] = {
                "symbol": symbol,
                "side": side,
                "entry_price": executed_price,
                "average_price": executed_price,
                "amount": amount,
                "fees_paid": fee,
                "unrealized_pnl": 0.0,
                "opened_at": datetime.now(UTC).isoformat()
            }
            logger.debug(f"Opened {side} on {symbol} at {executed_price}")

        self.current_prices[symbol] = executed_price
        return self.positions[symbol]

    def update_price(self, symbol: str, price: float):
        """Updates the current market price for a symbol, recalibrating Unrealized PnL."""
        self.current_prices[symbol] = price
        if symbol in self.positions:
            pos = self.positions[symbol]
            diff = price - pos["average_price"]
            pnl = diff * pos["amount"] if pos["side"] == "LONG" else -diff * pos["amount"]
            pos["unrealized_pnl"] = pnl

    def close_position(self, symbol: str, price: float, amount: float = None, is_maker: bool = False) -> Optional[dict]:
        """
        Closes a position for a symbol. If amount is None, closes the entire position.
        Supports partial closes.
        """
        if symbol not in self.positions:
            logger.warning(f"Cannot close {symbol}: No active position.")
            return None
            
        pos = self.positions[symbol]
        close_amount = amount if amount is not None else pos["amount"]

        if close_amount > pos["amount"]:
            logger.warning(f"Requested close amount {close_amount} > active {pos['amount']}. Closing all.")
            close_amount = pos["amount"]

        # When closing a LONG, I simulate a MARKET SELL, which means worst price (lower).
        # When closing a SHORT, I simulate a MARKET BUY, which means worst price (higher).
        close_side = "SHORT" if pos["side"] == "LONG" else "LONG" 
        executed_price, fee_pct = self.simulate_execution(price, close_side, is_maker)

        notional_exit = executed_price * close_amount
        fee = notional_exit * fee_pct
        self.balance -= fee

        # Calculate PnL (Gross)
        diff = executed_price - pos["average_price"]
        gross_pnl = diff * close_amount if pos["side"] == "LONG" else -diff * close_amount
        
        # Calculate proportional entry fees for the amount being closed
        proportional_entry_fees = (pos["fees_paid"] / pos["amount"]) * close_amount if pos["amount"] > 0 else 0
        
        # Net PnL accounts for entry and exit fees
        net_pnl = gross_pnl - proportional_entry_fees - fee
        
        self.balance += gross_pnl # Add the gross PnL to balance, fees are subtracted separately

        trade_record = {
            "symbol": symbol,
            "side": pos["side"],
            "entry_price": pos["average_price"],
            "exit_price": executed_price,
            "amount": close_amount,
            "gross_pnl": gross_pnl,
            "net_pnl": net_pnl,
            "total_fees": proportional_entry_fees + fee,
            "opened_at": pos["opened_at"],
            "closed_at": datetime.now(UTC).isoformat(),
            "is_partial": close_amount < pos["amount"]
        }

        # Update or Remove position
        if close_amount >= pos["amount"]:
            self.positions.pop(symbol)
        else:
            # Reduce position
            pos["amount"] -= close_amount
            pos["fees_paid"] -= proportional_entry_fees # Remaining fees stay with remaining amount
            # Recalculate unrealized PnL for the remaining portion
            self.update_price(symbol, self.current_prices.get(symbol, price))

        self.history.append(trade_record)
        self.total_realized_pnl += net_pnl
        
        # Prometheus Analytics
        bot_total_trades.inc()
        if net_pnl > 0:
            bot_winning_trades.inc()
        bot_realized_pnl.set(self.total_realized_pnl)
        
        logger.debug(f"Closed {close_amount} of {pos['side']} on {symbol}. Net PnL: {net_pnl:.2f}")
        return trade_record

    def calculate_equity(self) -> float:
        """Calculates total account equity including balance and unrealized PnL."""
        unrealized = sum(p["unrealized_pnl"] for p in self.positions.values())
        return self.balance + unrealized

    def get_state(self) -> dict:
        """Returns the complete portfolio state as a dict."""
        return {
            "balance": self.balance,
            "equity": self.calculate_equity(),
            "positions": self.positions,
            "history": self.history
        }
