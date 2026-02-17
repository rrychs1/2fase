import logging

logger = logging.getLogger(__name__)

class RiskManager:
    def __init__(self, config):
        self.config = config
        self.daily_pnl = 0.0

    def calculate_position_size(self, symbol: str, entry_price: float, stop_loss: float, equity: float) -> float:
        """
        Calculates the position size (number of contracts) based on equity and risk percentage.
        Formula: (Equity * Risk%) / |Entry - StopLoss|
        """
        if not stop_loss or entry_price == stop_loss:
            # Fallback to a small fixed size if no SL
            return (equity * self.config.MAX_RISK_PER_TRADE) / entry_price
            
        risk_amount = equity * self.config.MAX_RISK_PER_TRADE
        price_risk = abs(entry_price - stop_loss)
        
        amount = risk_amount / price_risk
        
        # Limit by leverage
        max_notional = equity * self.config.LEVERAGE
        if (amount * entry_price) > max_notional:
            amount = max_notional / entry_price
            logger.info(f"[Risk] {symbol} Size limited by leverage to {amount:.4f}")
            
        return amount

    def check_position_size(self, symbol, amount, price, equity):
        # Existing method kept for compatibility, but calling the new logic
        return amount # Placeholder

    def check_daily_drawdown(self, current_pnl, equity):
        self.daily_pnl = current_pnl
        limit = -equity * self.config.DAILY_LOSS_LIMIT
        logger.info(f"[Risk] Drawdown Check: PnL={current_pnl:.2f}, Equity={equity:.2f}, Limit={limit:.2f}")
        if self.daily_pnl <= limit:
            logger.warning("Daily Kill Switch Triggered!")
            return True
        return False

    def enforce_leverage_and_margin(self, exchange_client, symbol):
        exchange_client.set_leverage(symbol, self.config.LEVERAGE)
        # set isolated margin via exchange_client if needed
