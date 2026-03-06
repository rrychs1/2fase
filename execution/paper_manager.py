import json
import os
import logging
from datetime import datetime
from common.types import Side, SignalAction, Signal

logger = logging.getLogger(__name__)

class PaperManager:
    """
    Manages a virtual portfolio for paper trading.
    Persists state to virtual_account.json.
    """
    def __init__(self, initial_balance=10000.0):
        self.file_path = "virtual_account.json"
        is_new = not os.path.exists(self.file_path)
        self.state = self._load_state(initial_balance)
        if is_new:
            self._save_state()

    def _load_state(self, initial_balance):
        if os.path.exists(self.file_path):
            try:
                with open(self.file_path, "r") as f:
                    state = json.load(f)
                    # Ensure all fields exist
                    state.setdefault("balance", initial_balance)
                    state.setdefault("equity", initial_balance)
                    state.setdefault("positions", {})
                    state.setdefault("pending_orders", [])
                    state.setdefault("history", [])
                    return state
            except Exception:
                pass
        return {
            "balance": initial_balance,
            "equity": initial_balance,
            "positions": {}, 
            "pending_orders": [], 
            "history": []
        }

    def _save_state(self):
        with open(self.file_path, "w") as f:
            json.dump(self.state, f, indent=4)

    def get_equity(self, current_prices: dict):
        unrealized_pnl = 0
        for symbol, pos in self.state["positions"].items():
            price = current_prices.get(symbol, pos["entry_price"])
            pnl = (price - pos["entry_price"]) * pos["amount"]
            if pos["side"] == "SHORT":
                pnl = -pnl
            unrealized_pnl += pnl
        return self.state["balance"] + unrealized_pnl

    def execute_signal(self, signal: Signal):
        symbol = signal.symbol
        meta = signal.meta
        if signal.action in [SignalAction.ENTER_LONG, SignalAction.ENTER_SHORT]:
            if symbol in self.state["positions"]:
                return 
            
            side = "LONG" if signal.action == SignalAction.ENTER_LONG else "SHORT"
            
            # Initial DCA setup
            dca_levels = []
            if meta and 'dca_levels' in meta:
                dca_levels = meta['dca_levels']
            else:
                # Fallback: create 3 levels at 1.5% distance
                for i in range(1, 4):
                    price = signal.price * (1 - 0.015 * i) if side == "LONG" else signal.price * (1 + 0.015 * i)
                    dca_levels.append({"price": price, "amount": signal.amount / 3, "filled": False})

            self.state["positions"][symbol] = {
                "side": side,
                "entry_price": signal.price,
                "average_price": signal.price,
                "amount": signal.amount,
                "stop_loss": signal.stop_loss,
                "take_profit": signal.take_profit,
                "dca_levels": dca_levels,
                "is_active": True,
                "opened_at": datetime.utcnow().isoformat()
            }
            logger.info(f"[PAPER] Opened {side} on {symbol} at {signal.price}")

        elif signal.action == SignalAction.DCA_ADD:
            if symbol in self.state["positions"]:
                pos = self.state["positions"][symbol]
                old_total = pos["amount"]
                new_add = signal.amount
                
                # New Average Price
                pos["average_price"] = ((pos["average_price"] * old_total) + (signal.price * new_add)) / (old_total + new_add)
                pos["amount"] += new_add
                logger.info(f"[PAPER] {symbol} DCA Add at {signal.price}. New Avg: {pos['average_price']:.2f}")

        elif signal.action == SignalAction.GRID_PLACE:
            # Grid orders act like LIMIT orders
            self.state["pending_orders"].append({
                "symbol": symbol,
                "side": signal.side.value if hasattr(signal.side, 'value') else signal.side,
                "price": signal.price,
                "amount": signal.amount,
                "type": "grid"
            })
            logger.debug(f"[PAPER] Grid order placed: {signal.side} at {signal.price}")

        elif signal.action in [SignalAction.EXIT_LONG, SignalAction.EXIT_SHORT]:
            if symbol in self.state["positions"]:
                pos = self.state["positions"].pop(symbol)
                exit_price = signal.price if signal.price else pos["average_price"]
                pnl = (exit_price - pos["average_price"]) * pos["amount"]
                if pos["side"] == "SHORT":
                    pnl = -pnl
                
                self.state["balance"] += pnl
                self.state["history"].append({
                    "symbol": symbol,
                    "side": pos["side"],
                    "pnl": pnl,
                    "closed_at": datetime.utcnow().isoformat()
                })
                logger.info(f"[PAPER] Closed {pos['side']} on {symbol}. PnL: {pnl:.2f}")

        self._save_state()

    def update_positions(self, current_prices: dict):
        """Check for SL/TP hits and Pending Order fills in paper mode."""
        keys_to_remove = []
        orders_to_fill = []
        
        # 1. Check Pending Orders (Grid/DCA)
        for i, order in enumerate(self.state.get("pending_orders", [])):
            price = current_prices.get(order["symbol"])
            if not price: continue
            
            fill = False
            if order["side"] == "LONG" and price <= order["price"]:
                fill = True
            elif order["side"] == "SHORT" and price >= order["price"]:
                fill = True
            
            if fill:
                orders_to_fill.append(i)
                # Convert order to signal for consistency
                from common.types import Side
                sig = Signal(
                    symbol=order["symbol"],
                    action=SignalAction.ENTER_LONG if order["side"] == "LONG" else SignalAction.ENTER_SHORT,
                    side=Side.LONG if order["side"] == "LONG" else Side.SHORT,
                    price=order["price"],
                    amount=order["amount"]
                )
                # If already have position, treat as DCA_ADD
                if order["symbol"] in self.state["positions"]:
                    sig.action = SignalAction.DCA_ADD
                
                logger.info(f"[PAPER] Pending Order Filled: {order['side']} {order['symbol']} at {order['price']}")
                self.execute_signal(sig)

        # Remove filled orders
        if orders_to_fill:
            self.state["pending_orders"] = [o for i, o in enumerate(self.state["pending_orders"]) if i not in orders_to_fill]

        # 2. Check Active Positions (SL/TP)
        for symbol, pos in self.state["positions"].items():
            price = current_prices.get(symbol)
            if not price: continue
            
            closed = False
            exit_price = price
            
            if pos["side"] == "LONG":
                if pos.get("stop_loss") and price <= pos["stop_loss"]:
                    closed = True; exit_price = pos["stop_loss"]; logger.info(f"[PAPER] {symbol} SL Hit")
                elif pos.get("take_profit") and price >= pos["take_profit"]:
                    closed = True; exit_price = pos["take_profit"]; logger.info(f"[PAPER] {symbol} TP Hit")
            else:
                if pos.get("stop_loss") and price >= pos["stop_loss"]:
                    closed = True; exit_price = pos["stop_loss"]; logger.info(f"[PAPER] {symbol} SL Hit (Short)")
                elif pos.get("take_profit") and price <= pos["take_profit"]:
                    closed = True; exit_price = pos["take_profit"]; logger.info(f"[PAPER] {symbol} TP Hit (Short)")
            
            if closed:
                pnl = (exit_price - pos["average_price"]) * pos["amount"]
                if pos["side"] == "SHORT": pnl = -pnl
                self.state["balance"] += pnl
                keys_to_remove.append(symbol)
                self.state["history"].append({
                    "symbol": symbol, "side": pos["side"], "pnl": pnl, "type": "SL/TP", "closed_at": datetime.utcnow().isoformat()
                })

        for k in keys_to_remove:
            self.state["positions"].pop(k)
        
        if keys_to_remove or orders_to_fill:
            self._save_state()

    def append_equity_record(self, symbol, price, regime, signals_count, equity):
        """Phase 17: Log equity data for performance tracking."""
        try:
            record_path = os.getenv("PAPERS_FILE", "data/papers.jsonl")
            os.makedirs(os.path.dirname(record_path), exist_ok=True)
            
            record = {
                "ts": datetime.now().isoformat(),
                "symbol": symbol,
                "price": round(price, 2),
                "regime": regime,
                "signals_count": signals_count,
                "virtual_equity": round(equity, 2)
            }
            with open(record_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record) + "\n")
        except Exception as e:
            logger.warning(f"[PAPER] Failed to record equity: {e}")
