import logging
from datetime import date

logger = logging.getLogger(__name__)

class RiskManager:
    def __init__(self, config):
        self.config = config
        self.daily_pnl = 0.0
        self.last_reset_date = date.today()

    def _check_daily_reset(self):
        """Reset PnL tracking at midnight."""
        today = date.today()
        if today != self.last_reset_date:
            logger.info(f"[Risk] Daily reset: PnL {self.daily_pnl:.2f} -> 0.00 (new day: {today})")
            self.daily_pnl = 0.0
            self.last_reset_date = today

    def calculate_position_size(self, symbol: str, entry_price: float, stop_loss: float, equity: float) -> float:
        """
        Calculates the position size (number of contracts) based on equity and risk percentage.
        Formula: (Equity * Risk%) / |Entry - StopLoss|
        """
        if equity <= 0:
            logger.warning(f"[Risk] {symbol} Equity <= 0, returning 0 size.")
            return 0.0

        risk_amount = equity * self.config.MAX_RISK_PER_TRADE
        
        if not stop_loss or entry_price == stop_loss:
            # Fallback to a fixed % of equity if no SL
            amount = risk_amount / entry_price
        else:
            price_risk = abs(entry_price - stop_loss)
            amount = risk_amount / price_risk
        
        # Limit by leverage (Max Notional)
        max_notional = equity * self.config.LEVERAGE
        if (amount * entry_price) > max_notional:
            amount = max_notional / entry_price
            logger.info(f"[Risk] {symbol} Size limited by leverage to {amount:.4f}")
            
        # Min Notional Check
        min_notional = getattr(self.config, 'MIN_NOTIONAL_USD', 5.0)
        if (amount * entry_price) < min_notional:
            logger.warning(f"[Risk] {symbol} Size ({amount*entry_price:.2f}$) below min notional ({min_notional}$). Returning 0.")
            return 0.0
            
        return amount

    def check_position_size(self, symbol, amount, price, equity):
        return amount

    def check_daily_drawdown(self, current_pnl, equity):
        if not getattr(self.config, 'KILL_SWITCH_ENABLED', True):
            return False

        self._check_daily_reset()
        self.daily_pnl = current_pnl
        limit = -equity * self.config.DAILY_LOSS_LIMIT
        
        # Early warning at 50% of limit
        warning_threshold = limit * 0.5
        if self.daily_pnl <= warning_threshold and self.daily_pnl > limit:
            logger.warning(f"[Risk] ⚠️ Drawdown at 50% of limit: PnL={current_pnl:.2f}, Limit={limit:.2f}")
        
        if self.daily_pnl <= limit:
            logger.critical(f"Daily Kill Switch Triggered! PnL={current_pnl:.2f} <= Limit={limit:.2f}")
            return True
        return False

    def enforce_leverage_and_margin(self, exchange_client, symbol):
        exchange_client.set_leverage(symbol, self.config.LEVERAGE)
