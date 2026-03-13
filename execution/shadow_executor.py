import json
import os
import logging
from datetime import datetime, UTC
from common.types import Side, SignalAction, Signal

logger = logging.getLogger(__name__)

class ShadowExecutor:
    """
    Shadow Mode Execution.
    Simulates immediate fills at the given market price.
    Persists to virtual_account_shadow.json and shadow_trades.jsonl
    """
    def __init__(self, initial_balance=10000.0):
        self.file_path = "data/virtual_account_shadow.json"
        self.trades_log_path = "data/shadow_trades.jsonl"
        
        # Ensure directory exists
        os.makedirs(os.path.dirname(self.file_path), exist_ok=True)
        
        is_new = not os.path.exists(self.file_path)
        self.state = self._load_state(initial_balance)
        if is_new:
            self._save_state()

    def _load_state(self, initial_balance):
        if os.path.exists(self.file_path):
            try:
                with open(self.file_path, "r") as f:
                    state = json.load(f)
                    state.setdefault("balance", initial_balance)
                    state.setdefault("equity", initial_balance)
                    state.setdefault("positions", {})
                    state.setdefault("history", [])
                    return state
            except Exception:
                pass
        return {
            "balance": initial_balance,
            "equity": initial_balance,
            "positions": {}, 
            "history": []
        }

    def _save_state(self):
        with open(self.file_path, "w") as f:
            json.dump(self.state, f, indent=4)

    def get_equity(self, current_prices: dict):
        unrealized_pnl = self.get_account_pnl(current_prices)
        return self.state["balance"] + unrealized_pnl

    def get_account_pnl(self, current_prices: dict = None):
        """Calculates total unrealized PnL from all open positions."""
        unrealized_pnl = 0.0
        if not current_prices:
            return unrealized_pnl
            
        for symbol, pos in self.state["positions"].items():
            price = current_prices.get(symbol, pos["entry_price"])
            pnl = (price - pos["entry_price"]) * pos["amount"]
            if pos["side"] == "SHORT":
                pnl = -pnl
            unrealized_pnl += pnl
        return unrealized_pnl

    def get_position(self, symbol: str) -> dict:
        """Returns normalized position info for a symbol or empty dict."""
        pos = self.state["positions"].get(symbol)
        if pos:
            return {
                'symbol': symbol,
                'side': pos['side'],
                'is_active': True,
                'entry_price': pos['entry_price'],
                'average_price': pos['average_price'],
                'amount': pos['amount'],
                'unrealized_pnl': 0.0 # Will be calc'd externally or dynamically
            }
        return {}

    def fetch_positions(self):
        v_positions = []
        for symbol, pos in self.state["positions"].items():
            v_positions.append(self.get_position(symbol))
        return v_positions

    def execute_signal(self, signal: Signal):
        """Immediately fills the signal at signal.price."""
        symbol = signal.symbol
        if not signal.price or not signal.amount:
            logger.warning(f"[SHADOW] Missing price or amount for {symbol}")
            return None

        order_id = f"shdw_{int(datetime.now(UTC).timestamp()*1000)}"

        if signal.action.value in [SignalAction.ENTER_LONG.value, SignalAction.ENTER_SHORT.value]:
            if symbol in self.state["positions"]:
                return {"id": order_id, "status": "rejected", "reason": "Position exists"}
            
            side = "LONG" if signal.action.value == SignalAction.ENTER_LONG.value else "SHORT"
            
            self.state["positions"][symbol] = {
                "side": side,
                "entry_price": signal.price,
                "average_price": signal.price,
                "amount": signal.amount,
                "is_active": True,
                "opened_at": datetime.now(UTC).isoformat()
            }
            logger.info(f"[SHADOW] Executed {side} on {symbol} at {signal.price} (Size: {signal.amount})")
            self._log_trade(signal, "OPEN", 0.0)

        elif signal.action.value == SignalAction.DCA_ADD.value:
            if symbol in self.state["positions"]:
                pos = self.state["positions"][symbol]
                old_total = pos["amount"]
                new_add = signal.amount
                
                # New Average Price
                pos["average_price"] = ((pos["average_price"] * old_total) + (signal.price * new_add)) / (old_total + new_add)
                pos["amount"] += new_add
                logger.info(f"[SHADOW] {symbol} DCA filled at {signal.price}. New Avg: {pos['average_price']:.2f} Size: {pos['amount']:.4f}")
                self._log_trade(signal, "DCA", 0.0)

        elif signal.action.value == SignalAction.GRID_PLACE.value:
            # Shadow mode immediate fill for grids acts like a market buy if hit.
            # But grids are limits. Since shadow mode simulates immediate fills, we just treat it as DCA/Entry
            logger.info(f"[SHADOW] Grid order simulated at {signal.price} (Not tracked pending in Shadow mode yet)")

        elif signal.action.value in [SignalAction.EXIT_LONG.value, SignalAction.EXIT_SHORT.value]:
            if symbol in self.state["positions"]:
                pos = self.state["positions"].pop(symbol)
                pnl = (signal.price - pos["average_price"]) * pos["amount"]
                if pos["side"] == "SHORT":
                    pnl = -pnl
                
                self.state["balance"] += pnl
                hist_trade = {
                    "trade_id": order_id,
                    "symbol": symbol,
                    "side": pos["side"],
                    "price": signal.price,
                    "amount": pos["amount"],
                    "pnl": pnl,
                    "closed_at": datetime.now(UTC).isoformat()
                }
                self.state["history"].append(hist_trade)
                logger.info(f"[SHADOW] Closed {pos['side']} on {symbol} at {signal.price}. PnL: {pnl:.2f}")
                self._log_trade(signal, "CLOSE", pnl)

        self._save_state()
        return {"id": order_id, "status": "closed", "info": {"simulated": True, "mode": "shadow"}}

    def update_positions(self, current_prices: dict):
        """Shadow mode does not track limits natively. Can be expanded if needed."""
        pass

    def close_all_positions(self, current_prices: dict):
        """Emergency Close All"""
        symbols = list(self.state["positions"].keys())
        for sym in symbols:
            price = current_prices.get(sym)
            if price:
                pos = self.state["positions"][sym]
                action = SignalAction.EXIT_LONG if pos["side"] == "LONG" else SignalAction.EXIT_SHORT
                sig = Signal(symbol=sym, action=action, side=Side.LONG if pos["side"] == "LONG" else Side.SHORT, price=price, amount=pos["amount"])
                self.execute_signal(sig)
                
    def _log_trade(self, signal: Signal, action_type: str, pnl: float):
        record = {
            "ts": datetime.now(UTC).isoformat(),
            "mode": "SHADOW",
            "symbol": signal.symbol,
            "action": action_type,
            "side": signal.side.name if hasattr(signal.side, 'name') else signal.side,
            "price": signal.price,
            "amount": signal.amount,
            "pnl": pnl
        }
        with open(self.trades_log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
