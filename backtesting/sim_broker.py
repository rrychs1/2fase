"""
Simulated broker for backtesting.
Tracks positions, pending orders, fills, and applies fees/slippage.
All in-memory — no file I/O for speed.
"""
import logging
from dataclasses import dataclass, field
from typing import Optional
from common.types import Signal, SignalAction, Side

logger = logging.getLogger(__name__)


@dataclass
class SimPosition:
    """An open position in the simulated broker."""
    symbol: str
    side: str  # "LONG" or "SHORT"
    entry_price: float
    average_price: float
    amount: float
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    dca_levels: list = field(default_factory=list)


@dataclass
class SimOrder:
    """A pending limit/grid order."""
    symbol: str
    side: str  # "LONG" or "SHORT"
    price: float
    amount: float
    order_type: str = "grid"


@dataclass
class SimTrade:
    """A completed trade record."""
    symbol: str
    side: str
    entry_price: float
    exit_price: float
    amount: float
    pnl: float
    pnl_after_fees: float
    fees: float
    candle_index: int = 0


class SimBroker:
    """
    Simulated broker that processes signals and tracks portfolio state.
    
    Supports:
    - Market orders (instant fill at current price + slippage)
    - Limit / Grid orders (fill when price crosses order level)
    - SL / TP checking on each candle
    - Configurable fees and slippage
    """

    def __init__(
        self,
        initial_balance: float = 10000.0,
        maker_fee: float = 0.0004,   # 0.04%
        taker_fee: float = 0.0006,   # 0.06%
        slippage: float = 0.0001,    # 0.01%
    ):
        self.initial_balance = initial_balance
        self.balance = initial_balance
        self.maker_fee = maker_fee
        self.taker_fee = taker_fee
        self.slippage = slippage

        self.positions: dict[str, SimPosition] = {}
        self.pending_orders: list[SimOrder] = []
        self.trades: list[SimTrade] = []
        self.equity_curve: list[float] = []

    @property
    def equity(self) -> float:
        return self.balance

    def get_equity_with_unrealized(self, current_prices: dict) -> float:
        """Calculate equity including unrealized PnL."""
        unrealized = 0.0
        for symbol, pos in self.positions.items():
            price = current_prices.get(symbol, pos.average_price)
            pnl = (price - pos.average_price) * pos.amount
            if pos.side == "SHORT":
                pnl = -pnl
            unrealized += pnl
        return self.balance + unrealized

    def _apply_fee(self, notional: float, is_taker: bool = True) -> float:
        """Calculate fee for a given notional amount."""
        rate = self.taker_fee if is_taker else self.maker_fee
        return notional * rate

    def _apply_slippage(self, price: float, side: str) -> float:
        """Apply slippage to market orders."""
        if side == "LONG":
            return price * (1 + self.slippage)  # Buy slightly higher
        else:
            return price * (1 - self.slippage)  # Sell slightly lower

    def process_signal(self, signal: Signal, current_price: float, candle_idx: int = 0):
        """Process a signal from the strategy."""
        symbol = signal.symbol

        if signal.action in (SignalAction.ENTER_LONG, SignalAction.ENTER_SHORT):
            self._open_position(signal, current_price, candle_idx)

        elif signal.action == SignalAction.DCA_ADD:
            self._dca_add(signal, current_price, candle_idx)

        elif signal.action == SignalAction.GRID_PLACE:
            self._place_grid_order(signal)

        elif signal.action in (SignalAction.EXIT_LONG, SignalAction.EXIT_SHORT):
            self._close_position(symbol, current_price, candle_idx)

    def _open_position(self, signal: Signal, current_price: float, candle_idx: int):
        """Open a new position (market order)."""
        symbol = signal.symbol
        if symbol in self.positions:
            return  # Already have a position

        side = "LONG" if signal.action == SignalAction.ENTER_LONG else "SHORT"
        fill_price = self._apply_slippage(current_price, side)
        amount = signal.amount or 0.0

        if amount <= 0:
            return

        # Deduct taker fee
        fee = self._apply_fee(fill_price * amount, is_taker=True)
        self.balance -= fee

        # Extract DCA levels from meta
        dca_levels = []
        if signal.meta and "dca_levels" in signal.meta:
            dca_levels = signal.meta["dca_levels"]

        self.positions[symbol] = SimPosition(
            symbol=symbol,
            side=side,
            entry_price=fill_price,
            average_price=fill_price,
            amount=amount,
            stop_loss=signal.stop_loss,
            take_profit=signal.take_profit,
            dca_levels=dca_levels,
        )

    def _dca_add(self, signal: Signal, current_price: float, candle_idx: int):
        """Add to existing position (DCA)."""
        symbol = signal.symbol
        if symbol not in self.positions:
            return

        pos = self.positions[symbol]
        fill_price = current_price  # Limit fill — no slippage
        add_amount = signal.amount or 0.0

        if add_amount <= 0:
            return

        fee = self._apply_fee(fill_price * add_amount, is_taker=False)
        self.balance -= fee

        # Update average price
        old_notional = pos.average_price * pos.amount
        new_notional = fill_price * add_amount
        pos.amount += add_amount
        pos.average_price = (old_notional + new_notional) / pos.amount

    def _place_grid_order(self, signal: Signal):
        """Place a pending grid/limit order."""
        side = signal.side.value if hasattr(signal.side, "value") else str(signal.side)
        self.pending_orders.append(
            SimOrder(
                symbol=signal.symbol,
                side=side,
                price=signal.price,
                amount=signal.amount,
                order_type="grid",
            )
        )

    def _close_position(self, symbol: str, exit_price: float, candle_idx: int):
        """Close a position at the given price."""
        if symbol not in self.positions:
            return

        pos = self.positions.pop(symbol)
        slipped_price = self._apply_slippage(exit_price, "SHORT" if pos.side == "LONG" else "LONG")

        pnl = (slipped_price - pos.average_price) * pos.amount
        if pos.side == "SHORT":
            pnl = -pnl

        fee = self._apply_fee(slipped_price * pos.amount, is_taker=True)
        pnl_after_fees = pnl - fee
        self.balance += pnl_after_fees

        self.trades.append(
            SimTrade(
                symbol=symbol,
                side=pos.side,
                entry_price=pos.average_price,
                exit_price=slipped_price,
                amount=pos.amount,
                pnl=pnl,
                pnl_after_fees=pnl_after_fees,
                fees=fee,
                candle_index=candle_idx,
            )
        )

    def update_on_candle(self, candle: dict, candle_idx: int = 0):
        """
        Check pending orders and SL/TP on each new candle.
        
        candle: dict with keys 'open', 'high', 'low', 'close', 'symbol'
        """
        symbol = candle["symbol"]
        price_high = candle["high"]
        price_low = candle["low"]
        price_close = candle["close"]

        # 1. Check pending orders
        orders_to_remove = []
        for i, order in enumerate(self.pending_orders):
            if order.symbol != symbol:
                continue

            filled = False
            if order.side == "LONG" and price_low <= order.price:
                filled = True
            elif order.side == "SHORT" and price_high >= order.price:
                filled = True

            if filled:
                orders_to_remove.append(i)
                # If already have position, add as DCA
                if symbol in self.positions:
                    sig = Signal(
                        symbol=symbol,
                        action=SignalAction.DCA_ADD,
                        side=Side.LONG if order.side == "LONG" else Side.SHORT,
                        price=order.price,
                        amount=order.amount,
                    )
                    self._dca_add(sig, order.price, candle_idx)
                else:
                    action = SignalAction.ENTER_LONG if order.side == "LONG" else SignalAction.ENTER_SHORT
                    sig = Signal(
                        symbol=symbol,
                        action=action,
                        side=Side.LONG if order.side == "LONG" else Side.SHORT,
                        price=order.price,
                        amount=order.amount,
                    )
                    # For limit fills, don't apply slippage
                    fee = self._apply_fee(order.price * order.amount, is_taker=False)
                    self.balance -= fee
                    self.positions[symbol] = SimPosition(
                        symbol=symbol,
                        side=order.side,
                        entry_price=order.price,
                        average_price=order.price,
                        amount=order.amount,
                    )

        # Remove filled orders (reverse to keep indices valid)
        for i in sorted(orders_to_remove, reverse=True):
            self.pending_orders.pop(i)

        # 2. Check SL/TP for active positions
        if symbol in self.positions:
            pos = self.positions[symbol]

            if pos.side == "LONG":
                if pos.stop_loss and price_low <= pos.stop_loss:
                    self._close_position(symbol, pos.stop_loss, candle_idx)
                elif pos.take_profit and price_high >= pos.take_profit:
                    self._close_position(symbol, pos.take_profit, candle_idx)
            else:  # SHORT
                if pos.stop_loss and price_high >= pos.stop_loss:
                    self._close_position(symbol, pos.stop_loss, candle_idx)
                elif pos.take_profit and price_low <= pos.take_profit:
                    self._close_position(symbol, pos.take_profit, candle_idx)

    def get_position_dict(self, symbol: str) -> dict:
        """Return position as dict compatible with strategy market_state format."""
        if symbol not in self.positions:
            return {}

        pos = self.positions[symbol]
        return {
            "symbol": symbol,
            "side": pos.side,
            "is_active": True,
            "entry_price": pos.entry_price,
            "average_price": pos.average_price,
            "amount": pos.amount,
            "stop_loss": pos.stop_loss,
            "take_profit": pos.take_profit,
            "dca_levels": pos.dca_levels,
        }

    def force_close_all(self, current_prices: dict, candle_idx: int = 0):
        """Close all open positions at current prices (end of backtest)."""
        for symbol in list(self.positions.keys()):
            price = current_prices.get(symbol, self.positions[symbol].average_price)
            self._close_position(symbol, price, candle_idx)
        self.pending_orders.clear()
