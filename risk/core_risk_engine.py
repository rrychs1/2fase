import logging
from common.types import Signal, SignalAction

logger = logging.getLogger(__name__)

class CoreRiskEngine:
    def __init__(self, config, portfolio_state):
        """
        Initializes the Central Risk Engine.
        :param config: The configuration object containing risk limits.
        :param portfolio_state: A callable or dictionary representing the live state of the portfolio.
        """
        self.config = config
        self.portfolio_state = portfolio_state

    def get_state(self) -> dict:
        """Returns the dynamic state either from a callable or direct dict."""
        if callable(self.portfolio_state):
            return self.portfolio_state()
        return self.portfolio_state

    def validate_order(self, order: Signal) -> bool:
        """
        Called BEFORE execution.
        Must block orders violating ANY constraint.
        """
        state = self.get_state()
        positions = state.get("positions", {})
        balance = state.get("balance", 0.0)
        # Fallback to balance if equity isn't tracked explicitly in the state dict yet
        equity = state.get("equity", balance) 
        
        symbol = order.symbol
        amount = order.amount
        price = order.price or 0.0

        if equity <= 0:
            logger.error(f"[RiskEngine] Blocked {order.action.value} on {symbol}: Zero or negative equity.", extra={"event": "RiskLimitBreached", "symbol": symbol, "reason": "ZeroEquity"})
            return False

        # 1. Max open positions
        active_positions = [sym for sym, pos in positions.items() if isinstance(pos, dict) and pos.get('is_active', False)]
        max_open = getattr(self.config, 'RISK_MAX_OPEN_POSITIONS', 5)
        # If it's a new entry and we have reached the max open limit
        if order.action in (SignalAction.ENTER_LONG, SignalAction.ENTER_SHORT) and symbol not in active_positions:
            if len(active_positions) >= max_open:
                logger.error(f"[RiskEngine] Blocked {order.action.value} on {symbol}: Max open positions ({max_open}) limit breached.", extra={"event": "RiskLimitBreached", "symbol": symbol, "reason": "MaxOpenPositions"})
                return False

        # 2. Max exposure per symbol
        max_pos_limit = getattr(self.config, 'RISK_MAX_POSITION_PER_SYMBOL', 0.1)
        max_notional_per_symbol = equity * max_pos_limit
        
        current_pos = positions.get(symbol, {})
        current_amount = current_pos.get('amount', 0.0)
        current_entry = current_pos.get('entry_price', 0.0)
        current_notional = current_amount * current_entry
        
        new_notional = amount * price
        
        # Allow exits or risk-reducing orders
        if order.action not in (SignalAction.EXIT_LONG, SignalAction.EXIT_SHORT):
            if current_notional + new_notional > max_notional_per_symbol:
                logger.error(f"[RiskEngine] Blocked {order.action.value} on {symbol}: Max exposure per symbol breached. "
                             f"Limit: {max_pos_limit*100}%. Current Notional: {current_notional:.2f}, Attempted Added Notional: {new_notional:.2f}", extra={"event": "RiskLimitBreached", "symbol": symbol, "reason": "MaxPositionExposure"})
                return False

        # 3. Max total exposure
        max_total_limit = getattr(self.config, 'MAX_TOTAL_EXPOSURE', 0.5)
        overall_notional = sum(
            p.get('amount', 0.0) * p.get('entry_price', 0.0) 
            for p in positions.values() if isinstance(p, dict) and p.get('is_active')
        )
        
        if order.action not in (SignalAction.EXIT_LONG, SignalAction.EXIT_SHORT):
            if overall_notional + new_notional > equity * max_total_limit:
                logger.error(f"[RiskEngine] Blocked {order.action.value} on {symbol}: Total max exposure breached. "
                             f"Limit: {max_total_limit*100}% of Equity.", extra={"event": "RiskLimitBreached", "symbol": symbol, "reason": "MaxTotalExposure"})
                return False

        return True

    def check_global_limits(self):
        """
        Runs continuously (or per cycle). Logs warnings for operational limits.
        """
        state = self.get_state()
        balance = state.get("balance", 0.0)
        equity = state.get("equity", balance)

    def should_shutdown(self) -> bool:
        """
        Returns True if system must stop trading immediately
        """
        state = self.get_state()
        balance = state.get("balance", 0.0)
        equity = state.get("equity", balance)
        
        if equity <= 0 and balance > 0:
             return True # Something is terribly wrong

        hwm = state.get("high_water_mark", balance)
        drawdown = (hwm - equity) / hwm if hwm > 0 else 0.0
        max_drawdown = getattr(self.config, 'RISK_MAX_DRAWDOWN', 0.2)
        
        if drawdown > max_drawdown:
            logger.critical(f"[RiskEngine] HARD KILL SWITCH TRIGGERED: Max drawdown breached! {drawdown*100:.2f}% > {max_drawdown*100:.2f}%", extra={"event": "KillSwitchTriggered", "symbol": "SYSTEM", "reason": "MaxDrawdown", "drawdown_pct": float(drawdown*100)})
            from monitoring.metrics import bot_system_health
            bot_system_health.set(0)
            return True
            
        start_balance = state.get("start_of_day_balance", balance)
        daily_loss = (start_balance - equity) / start_balance if start_balance > 0 else 0.0
        max_daily_loss = getattr(self.config, 'RISK_MAX_DAILY_LOSS', 0.05)
        
        if daily_loss > max_daily_loss:
            logger.critical(f"[RiskEngine] HARD KILL SWITCH TRIGGERED: Max daily loss breached! {daily_loss*100:.2f}% > {max_daily_loss*100:.2f}%", extra={"event": "KillSwitchTriggered", "symbol": "SYSTEM", "reason": "MaxDailyLoss"})
            from monitoring.metrics import bot_system_health
            bot_system_health.set(0)
            return True
            
        return False
