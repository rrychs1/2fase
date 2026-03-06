
import time
import logging
import asyncio
from typing import Optional, Dict
from enum import Enum
from logging_monitoring.telegram_bot import TelegramBot

logger = logging.getLogger(__name__)

class AlertLevel(Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    TRADE = "TRADE"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"

class TelegramAlertService:
    """
    Centralized service for Telegram notifications.
    Provides deduplication, rate limiting, and silent error handling.
    """
    def __init__(self, bot: Optional[TelegramBot] = None):
        self.bot = bot or TelegramBot()
        self.sent_alerts: Dict[str, float] = {}  # {dedup_key: last_sent_timestamp}
        self.default_dedup_window = 300  # Default 5 minutes
        
        # Phase 21: Critical Error Separation & Cooldown
        self.last_critical_error = ""
        self.last_critical_ts = 0.0
        self.critical_cooldown = 900 # 15 minutes
        
        # Reliability Phase 14: Filtering and Aggregation
        self.min_telegram_level = AlertLevel.INFO # Phase 21: Allow INFO to see startup ping
        self.aggregation_buffer: Dict[str, Dict] = {}
        
    async def verify_bot(self):
        """Proxy for original verify_bot."""
        return await self.bot.verify_bot()
        
    def is_healthy(self) -> bool:
        """Checks if the underlying bot is healthy."""
        return self.bot.is_healthy()

    async def send_alert(self, message: str, level: AlertLevel = AlertLevel.INFO, 
                         dedup_key: Optional[str] = None, window: Optional[int] = None,
                         force: bool = False):
        """
        Sends an alert through Telegram with retry logic and deduplication.
        Also persists the alert to a local file for dashboard history.
        """
        # Phase 16: Always persist locally even if filtered for Telegram
        self._persist_alert(message, level, dedup_key)

        if not self.bot.enabled:
            return

        # Phase 21: Backoff if Telegram is known to be down (Health Check Cache)
        if not self.bot.is_healthy():
            logger.warning(f"[ALERTS] Telegram is marked UNHEALTHY. Skipping: {message[:50]}...")
            return

        # Phase 14: Filter by level unless forced (e.g. for Trades or Startup)
        level_values = {l: i for i, l in enumerate(AlertLevel)}
        if not force and level_values[level] < level_values[self.min_telegram_level]:
            logger.debug(f"[ALERTS] Filtering out {level.value} alert: {message[:50]}...")
            return

        now = time.time()
        
        # 1. Deduplication / Rate Limiting logic
        if dedup_key:
            last_sent = self.sent_alerts.get(dedup_key, 0)
            dedup_window = window if window is not None else self.default_dedup_window
            if now - last_sent < dedup_window:
                # Add to aggregation buffer instead of just dropping
                summary = f"[{level.value}] {message[:100]}"
                if summary not in self.aggregation_buffer:
                    self.aggregation_buffer[summary] = {"count": 1, "level": level, "first_seen": now}
                else:
                    self.aggregation_buffer[summary]["count"] += 1
                logger.debug(f"[ALERTS] Grouped repeated alert ({dedup_key}). Total: {self.aggregation_buffer[summary]['count']}")
                return

        # 2. Sending with Styles and Levels
        max_retries = 2
        styled_message = self._apply_style(message, level)
        
        for attempt in range(max_retries + 1):
            try:
                if level in [AlertLevel.ERROR, AlertLevel.CRITICAL]:
                    await self.bot.send_error_alert(styled_message)
                else:
                    await self.bot.send_message(styled_message)
                
                # Success: Update deduplication table
                if dedup_key:
                    self.sent_alerts[dedup_key] = now
                return
                
            except Exception as e:
                if attempt < max_retries:
                    wait_time = (attempt + 1) * 3
                    logger.warning(f"[ALERTS] Send failed (attempt {attempt+1}): {e}. Retrying in {wait_time}s...")
                    await asyncio.sleep(wait_time)
                else:
                    # Final failure: Log but do not raise (silent failure)
                    logger.error(f"[ALERTS] Persistent failure sending to Telegram after {max_retries} retries: {e}")

    async def critical(self, msg: str, dedup_key: Optional[str] = None):
        """Sends a critical alert with its own cooldown logic."""
        now = time.time()
        # If it's the SAME message within 15 mins, skip sending to Telegram (but still log)
        if msg == self.last_critical_error and (now - self.last_critical_ts) < self.critical_cooldown:
            logger.debug(f"[ALERTS] Skipping duplicate critical error: {msg[:50]}...")
            self._persist_alert(f"[COOLDOWN SKIP] {msg}", AlertLevel.CRITICAL, dedup_key)
            return

        self.last_critical_error = msg
        self.last_critical_ts = now
        await self.send_alert(msg, AlertLevel.CRITICAL, dedup_key, force=True)

    async def flush_alerts(self):
        """Sends a summary of all aggregated alerts in the buffer."""
        if not self.aggregation_buffer:
            return

        summary_msg = "📉 **Resumen de Alertas Agrupadas**\n\n"
        for summary, data in self.aggregation_buffer.items():
            summary_msg += f"• {summary}\n  (Repetido {data['count']} veces)\n"
        
        self.aggregation_buffer = {} # Clear buffer
        await self.bot.send_message(summary_msg)

    # Helper methods for cleaner calls
    async def info(self, msg: str, dedup_key: Optional[str] = None, force: bool = False):
        await self.send_alert(msg, AlertLevel.INFO, dedup_key, force=force)

    async def warning(self, msg: str, dedup_key: Optional[str] = None):
        await self.send_alert(msg, AlertLevel.WARNING, dedup_key)

    async def error(self, msg: str, dedup_key: Optional[str] = None):
        await self.send_alert(msg, AlertLevel.ERROR, dedup_key)


    async def trade(self, symbol: str, side: str, price: float, amount: float, strategy: str):
        """Specifically for trades - usually we don't dedup these unless requested."""
        msg = f"📉 **TRADE**: {side} {symbol} @ {price} ({strategy})"
        self._persist_alert(msg, AlertLevel.TRADE, f"trade_{symbol}_{side}")

        if not self.bot.enabled: return
        try:
            await self.bot.send_trade_alert(symbol, side, price, amount, strategy)
        except Exception as e:
            logger.error(f"[ALERTS] Failed to send trade alert: {e}")

    def _apply_style(self, message: str, level: AlertLevel) -> str:
        """Apply visual markers and headers based on level."""
        prefixes = {
            AlertLevel.INFO: "ℹ️ **INFO**\n",
            AlertLevel.WARNING: "⚠️ **WARNING**\n",
            AlertLevel.TRADE: "📉 **TRADE**\n",
            AlertLevel.ERROR: "❌ **ERROR**\n",
            AlertLevel.CRITICAL: "🚨 **CRITICAL ERROR** 🚨\n"
        }
        
        prefix = prefixes.get(level, "")
        if level == AlertLevel.CRITICAL:
            return f"{prefix}\n{message}\n\n_Acción requerida inmediata._"
        return f"{prefix}{message}"

    def _persist_alert(self, message: str, level: AlertLevel, key: Optional[str]):
        """Append alert to a local jsonl file for dashboard consumption."""
        import os
        import json
        from datetime import datetime

        alert_path = "data/alerts.jsonl"
        try:
            # Ensure directory exists
            os.makedirs(os.path.dirname(alert_path), exist_ok=True)
            
            record = {
                "ts": datetime.now().isoformat(),
                "level": level.value,
                "msg": message,
                "key": key
            }
            with open(alert_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record) + "\n")
        except Exception as e:
            logger.debug(f"[ALERTS] Failed to persist alert: {e}")
