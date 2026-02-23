import logging
from datetime import date

logger = logging.getLogger(__name__)

class RiskManager:
    def __init__(self, config):
        self.config = config
        self.daily_pnl = 0.0
        self.last_reset_date = date.today()
        self.reference_equity = 0.0
        self.last_cycle_equity = 0.0
        self.is_safe_mode = False
        self.drift_threshold = getattr(config, 'EQUITY_DRIFT_THRESHOLD', 0.05) # 5% default

    def _check_daily_reset(self):
        """Reset PnL tracking at midnight."""
        today = date.today()
        if today != self.last_reset_date:
            logger.info(f"[Risk] Daily reset: PnL {self.daily_pnl:.2f} -> 0.00 (new day: {today})")
            self.daily_pnl = 0.0
            self.last_reset_date = today

    def sync_reference_equity(self, equity: float, unrealized_pnl: float):
        """
        Maintains a consistent equity reference for the entire cycle.
        Activates safe mode if equity is invalid.
        """
        if equity is None or equity <= 0:
            if not self.is_safe_mode:
                logger.critical(f"[Risk] INVALID EQUITY DETECTED: {equity}. ACTIVATING SAFE MODE.")
                self.is_safe_mode = True
            self.reference_equity = 0.0
            return

        # Recovery from safe mode if equity becomes positive again
        if self.is_safe_mode and equity > 0:
            logger.info(f"[Risk] Equity recovered to {equity}. Deactivating safe mode.")
            self.is_safe_mode = False

        self.reference_equity = equity
        
        # Monitor Drift
        if self.last_cycle_equity > 0:
            drift = abs(equity - self.last_cycle_equity) / self.last_cycle_equity
            if drift > self.drift_threshold:
                logger.warning(f"[Risk] SIGNIFICANT EQUITY DRIFT DETECTED: {drift*100:.2f}% "
                               f"({self.last_cycle_equity:.2f} -> {equity:.2f}) without recorded trades.")
                # We don't activate safe mode automatically for drift, but we log strongly.
        
        self.last_cycle_equity = equity

    def calculate_position_size(self, symbol: str, entry_price: float, stop_loss: float, exchange_client=None) -> float:
        """
        Calculates position size using the consistent reference equity.
        Validates against exchange filters if client is provided.
        """
        equity = self.reference_equity
        if equity <= 0 or self.is_safe_mode:
            logger.warning(f"[Risk] {symbol} Skipping size calc (Equity={equity}, SafeMode={self.is_safe_mode})")
            return 0.0

        risk_amount = equity * self.config.MAX_RISK_PER_TRADE
        
        if not stop_loss or entry_price == stop_loss:
            amount = risk_amount / entry_price
        else:
            price_risk = abs(entry_price - stop_loss)
            amount = risk_amount / price_risk
        
        # Limit by leverage
        max_notional = equity * self.config.LEVERAGE
        if (amount * entry_price) > max_notional:
            amount = max_notional / entry_price
            logger.info(f"[Risk] {symbol} Size limited by leverage to {amount:.4f}")
            
        # Exchange Filter Validation
        if exchange_client:
            is_valid, reason = exchange_client.validate_order_filters(symbol, amount, entry_price)
            if not is_valid:
                logger.warning(f"[Risk] {symbol} Order validation failed: {reason}. Returning 0 size.")
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
