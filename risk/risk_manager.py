import logging
import json
import os
from datetime import date, datetime

logger = logging.getLogger(__name__)

class RiskManager:
    def __init__(self, config):
        self.config = config
        self.daily_pnl = 0.0
        self.last_reset_date = date.today()
        self.day_start_equity = 0.0
        self.reference_equity = 0.0
        self.last_cycle_equity = 0.0
        self.is_safe_mode = False
        self.is_high_caution = False # Phase 5: halted opening due to CB or Alerts
        self.drift_threshold = getattr(config, 'EQUITY_DRIFT_THRESHOLD', 0.05) # 5% default
        self.is_kill_switch_active = False
        self.last_kill_switch_alert = 0
        self.alert_throttle_seconds = 3600 # 1 hour default
        self.reconcile_interval = 20 # Every 20 iterations
        self.state_file = "risk_state.json"
        self.load_state()

    def needs_reconciliation(self, iteration_count: int) -> bool:
        """Check if it's time to reconcile internal state with exchange."""
        return iteration_count > 0 and (iteration_count % self.reconcile_interval == 0)

    def _check_daily_reset(self, current_equity=0.0):
        """Reset PnL and day_start_equity tracking at midnight."""
        today = date.today()
        if today != self.last_reset_date:
            logger.info(f"[Risk] Daily reset: PnL {self.daily_pnl:.2f} -> 0.00 (new day: {today})")
            self.daily_pnl = 0.0
            self.day_start_equity = current_equity
            self.last_reset_date = today
            self.is_kill_switch_active = False # Reset kill switch on new day
            self.save_state()

    def load_state(self):
        """Load persistent risk state from JSON."""
        if not os.path.exists(self.state_file):
            return
        try:
            with open(self.state_file, 'r') as f:
                state = json.load(f)
                self.day_start_equity = float(state.get('day_start_equity', 0.0))
                self.last_reset_date = date.fromisoformat(state.get('last_reset_date', str(date.today())))
                self.is_kill_switch_active = bool(state.get('is_kill_switch_active', False))
                logger.info(f"[Risk] State loaded: day_start={self.day_start_equity}, kill_switch={self.is_kill_switch_active}")
        except Exception as e:
            logger.warning(f"[Risk] Failed to load state: {e}")

    def save_state(self):
        """Save persistent risk state to JSON."""
        try:
            state = {
                'day_start_equity': self.day_start_equity,
                'last_reset_date': self.last_reset_date.isoformat(),
                'is_kill_switch_active': self.is_kill_switch_active,
                'updated_at': datetime.now().isoformat()
            }
            with open(self.state_file, 'w') as f:
                json.dump(state, f, indent=2)
        except Exception as e:
            logger.warning(f"[Risk] Failed to save state: {e}")

    def sync_reference_equity(self, equity: float, unrealized_pnl: float):
        """
        Maintains a consistent equity reference for the entire cycle.
        Activates safe mode if equity is invalid or drift is too high.
        Returns (drift_alert_needed, drift_value)
        """
        drift_alert = False
        drift_val = 0.0

        if equity is None or equity <= 0:
            if not self.is_safe_mode:
                logger.critical(f"[Risk] INVALID EQUITY DETECTED: {equity}. ACTIVATING SAFE MODE.")
                self.is_safe_mode = True
            self.reference_equity = 0.0
            return drift_alert, 0.0

        # Recovery from safe mode if equity becomes positive again (ONLY if it was due to invalid equity, not drift)
        # For simplicity, we allow manual reset of is_safe_mode or recovery if equity > 0
        if self.is_safe_mode and equity > 0 and self.reference_equity == 0:
            logger.info(f"[Risk] Equity recovered to {equity}. Deactivating safe mode.")
            self.is_safe_mode = False

        self.reference_equity = equity
        
        # Initialize day_start_equity if 0
        if self.day_start_equity <= 0:
            self.day_start_equity = equity
            self.save_state()

        # Monitor Drift
        if self.last_cycle_equity > 0:
            drift_val = abs(equity - self.last_cycle_equity) / self.last_cycle_equity
            if drift_val > self.drift_threshold:
                logger.warning(f"[Risk] SIGNIFICANT EQUITY DRIFT: {drift_val*100:.2f}% "
                               f"({self.last_cycle_equity:.2f} -> {equity:.2f})")
                
                if not self.is_safe_mode:
                    self.is_safe_mode = True
                    drift_alert = True
        
        self.last_cycle_equity = equity
        return drift_alert, drift_val

    def calculate_position_size(self, symbol: str, entry_price: float, stop_loss: float, exchange_client=None) -> float:
        """
        Calculates position size using the consistent reference equity.
        Validates against exchange filters and caution modes.
        """
        equity = self.reference_equity
        if equity <= 0 or self.is_safe_mode or self.is_high_caution:
            reason = "Equity <= 0" if equity <= 0 else ("Safe Mode" if self.is_safe_mode else "High Caution")
            logger.warning(f"[Risk] {symbol} Skipping size calc: {reason}")
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

        self._check_daily_reset(equity)
        
        # Priority 1: If Kill Switch is already active, stay active
        if self.is_kill_switch_active:
            self._throttle_alert("KILL SWITCH STILL ACTIVE: Blocking all new entries.")
            return True

        # Use day_start_equity as reference if available, otherwise current equity
        ref_equity = self.day_start_equity if self.day_start_equity > 0 else equity
        if ref_equity <= 0: return False

        self.daily_pnl = current_pnl
        limit = -ref_equity * self.config.DAILY_LOSS_LIMIT
        
        # Early warning at 50% of limit
        warning_threshold = limit * 0.5
        if self.daily_pnl <= warning_threshold and self.daily_pnl > limit:
            logger.warning(f"[Risk] ⚠️ Drawdown at 50% of limit: PnL={current_pnl:.2f}, Limit={limit:.2f} (Ref={ref_equity:.2f})")
        
        if self.daily_pnl <= limit:
            if not self.is_kill_switch_active:
                logger.critical(f"Daily Kill Switch Triggered! PnL={current_pnl:.2f} <= Limit={limit:.2f}")
                self.is_kill_switch_active = True
                self.save_state()
            return True
        return False

    def _throttle_alert(self, message):
        """Logs message only once every alert_throttle_seconds."""
        import time
        now = time.time()
        if now - self.last_kill_switch_alert > self.alert_throttle_seconds:
            logger.warning(f"[Risk] {message}")
            self.last_kill_switch_alert = now
            return True
        return False

    def enforce_leverage_and_margin(self, exchange_client, symbol):
        exchange_client.set_leverage(symbol, self.config.LEVERAGE)
