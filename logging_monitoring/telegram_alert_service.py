"""
Telegram Alert Service — centralized notifications with dedup,
rate limiting, and granular .env control.

Environment flags:
    TELEGRAM_ENABLED=true/false        Master switch (in telegram_bot.py)
    ENABLE_TELEGRAM_ALERTS=true/false  Trade/error/warning alerts
    ENABLE_TELEGRAM_STATUS=true/false  Periodic status updates

If all flags are false, alerts are still persisted locally to
data/alerts.jsonl for dashboard consumption.
"""
import os
import time
import json
import logging
import asyncio
from typing import Optional, Dict
from enum import Enum
from datetime import datetime
from logging_monitoring.telegram_bot import TelegramBot

logger = logging.getLogger(__name__)


class AlertLevel(Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    TRADE = "TRADE"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


def _is_true(val: str | None) -> bool:
    """Parse a boolean env var."""
    return str(val).strip().lower() in ("true", "1", "yes")


class TelegramAlertService:
    """
    Centralized service for Telegram notifications.

    Features:
      - Respects ENABLE_TELEGRAM_ALERTS and ENABLE_TELEGRAM_STATUS
      - Deduplication with configurable windows
      - Rate limiting with aggregation buffer
      - Critical error cooldowns (15 min)
      - Local persistence to alerts.jsonl (always, regardless of flags)
      - NEVER raises exceptions — all errors are logged

    Usage:
        alerts = TelegramAlertService()     # reads .env automatically
        await alerts.info("Bot started")    # sends if enabled
        await alerts.trade(...)             # sends if ENABLE_TELEGRAM_ALERTS
        await alerts.critical("...")        # always sends (if Telegram available)
    """

    def __init__(self, bot: Optional[TelegramBot] = None):
        self.bot = bot or TelegramBot()

        # ── Granular flags ───────────────────────────────────
        self.alerts_enabled = _is_true(os.getenv("ENABLE_TELEGRAM_ALERTS", "true"))
        self.status_enabled = _is_true(os.getenv("ENABLE_TELEGRAM_STATUS", "true"))

        # ── Deduplication ────────────────────────────────────
        self.sent_alerts: Dict[str, float] = {}
        self.default_dedup_window = 300  # 5 minutes

        # ── Critical error cooldown ──────────────────────────
        self.last_critical_error = ""
        self.last_critical_ts = 0.0
        self.critical_cooldown = 900  # 15 minutes

        # ── Aggregation buffer ───────────────────────────────
        self.min_telegram_level = AlertLevel.INFO
        self.aggregation_buffer: Dict[str, Dict] = {}

        if not self.bot.enabled:
            logger.info("[ALERTS] Telegram disabled — alerts will only be persisted locally.")
        else:
            modes = []
            if self.alerts_enabled:
                modes.append("alerts")
            if self.status_enabled:
                modes.append("status")
            logger.info("[ALERTS] Telegram active for: %s", ", ".join(modes) if modes else "nothing (both flags off)")

    # ── Read-only properties ─────────────────────────────────

    @property
    def enabled(self) -> bool:
        """True if the bot is connected and at least one flag is on."""
        return self.bot.enabled and (self.alerts_enabled or self.status_enabled)

    def is_healthy(self) -> bool:
        """Checks if the underlying bot connection is healthy."""
        return self.bot.is_healthy()

    # ── Core send method ─────────────────────────────────────

    async def send_alert(self, message: str, level: AlertLevel = AlertLevel.INFO,
                         dedup_key: Optional[str] = None, window: Optional[int] = None,
                         force: bool = False):
        """
        Send an alert through Telegram with dedup and rate limiting.
        Always persists locally regardless of Telegram state.
        """
        # Always persist locally (dashboard reads this)
        self._persist_alert(message, level, dedup_key)

        # Check if Telegram sending is appropriate
        if not self._should_send_telegram(level, force):
            return

        # Deduplication
        now = time.time()
        if dedup_key:
            last_sent = self.sent_alerts.get(dedup_key, 0)
            dedup_window = window if window is not None else self.default_dedup_window
            if now - last_sent < dedup_window:
                self._buffer_aggregation(message, level)
                return

        # Send with retry
        styled_message = self._apply_style(message, level)
        await self._send_with_retry(styled_message, level, dedup_key, now)

    # ── Convenience methods ──────────────────────────────────

    async def info(self, msg: str, dedup_key: Optional[str] = None, force: bool = False):
        """Send an INFO level alert."""
        await self.send_alert(msg, AlertLevel.INFO, dedup_key, force=force)

    async def warning(self, msg: str, dedup_key: Optional[str] = None):
        """Send a WARNING level alert."""
        await self.send_alert(msg, AlertLevel.WARNING, dedup_key)

    async def error(self, msg: str, dedup_key: Optional[str] = None):
        """Send an ERROR level alert."""
        await self.send_alert(msg, AlertLevel.ERROR, dedup_key)

    async def critical(self, msg: str, dedup_key: Optional[str] = None):
        """Send a CRITICAL alert with its own cooldown logic."""
        now = time.time()
        if msg == self.last_critical_error and (now - self.last_critical_ts) < self.critical_cooldown:
            logger.debug("[ALERTS] Skipping duplicate critical: %s", msg[:50])
            self._persist_alert(f"[COOLDOWN SKIP] {msg}", AlertLevel.CRITICAL, dedup_key)
            return
        self.last_critical_error = msg
        self.last_critical_ts = now
        await self.send_alert(msg, AlertLevel.CRITICAL, dedup_key, force=True)

    async def trade(self, symbol: str, side: str, price: float,
                    amount: float, strategy: str):
        """Send a trade alert — controlled by ENABLE_TELEGRAM_ALERTS."""
        msg = f"TRADE: {side} {symbol} @ {price:.2f} ({strategy})"
        self._persist_alert(msg, AlertLevel.TRADE, f"trade_{symbol}_{side}")

        if not self.bot.enabled or not self.alerts_enabled:
            return
        try:
            await self.bot.send_trade_alert(symbol, side, price, amount, strategy)
        except Exception as e:
            logger.warning("[ALERTS] Failed to send trade alert: %s", e)

    async def send_status_update(self, equity: float, pnl: float):
        """Send periodic status — controlled by ENABLE_TELEGRAM_STATUS."""
        if not self.bot.enabled or not self.status_enabled:
            return
        try:
            await self.bot.send_status_update(equity, pnl)
        except Exception as e:
            logger.warning("[ALERTS] Failed to send status update: %s", e)

    async def verify_bot(self) -> str | None:
        """Verify bot token. Returns username or None."""
        try:
            return await self.bot.verify_bot()
        except Exception as e:
            logger.warning("[ALERTS] Failed to verify Telegram bot: %s", e)
            return None

    async def flush_alerts(self):
        """Send a summary of aggregated alerts in the buffer."""
        if not self.aggregation_buffer:
            return
        if not self.bot.enabled or not self.alerts_enabled:
            self.aggregation_buffer = {}
            return

        summary_msg = "Resumen de Alertas Agrupadas\n\n"
        for summary, data in self.aggregation_buffer.items():
            summary_msg += f"- {summary}\n  (Repetido {data['count']} veces)\n"

        self.aggregation_buffer = {}
        try:
            await self.bot.send_message(summary_msg)
        except Exception as e:
            logger.warning("[ALERTS] Failed to flush alerts: %s", e)

    async def close(self):
        """Close the underlying bot session."""
        await self.bot.close()

    # ── Backwards compatibility ──────────────────────────────

    async def send_error_alert(self, msg: str):
        """Backwards-compatible error alert."""
        await self.error(msg)

    # ── Private helpers ──────────────────────────────────────

    def _should_send_telegram(self, level: AlertLevel, force: bool) -> bool:
        """Decide if this alert should be sent to Telegram."""
        if not self.bot.enabled:
            return False
        if not self.bot.is_healthy():
            logger.debug("[ALERTS] Telegram unhealthy — skipping send.")
            return False

        # CRITICAL always goes through (if bot is healthy)
        if force or level == AlertLevel.CRITICAL:
            return True

        # Status updates are controlled by their own flag
        if level == AlertLevel.INFO:
            return self.alerts_enabled or self.status_enabled

        # All other levels (WARNING, ERROR, TRADE) respect alerts flag
        return self.alerts_enabled

    def _buffer_aggregation(self, message: str, level: AlertLevel):
        """Add a deduplicated message to the aggregation buffer."""
        summary = f"[{level.value}] {message[:100]}"
        if summary not in self.aggregation_buffer:
            self.aggregation_buffer[summary] = {"count": 1, "level": level, "first_seen": time.time()}
        else:
            self.aggregation_buffer[summary]["count"] += 1

    async def _send_with_retry(self, styled_message: str, level: AlertLevel,
                               dedup_key: Optional[str], now: float):
        """Send a message with up to 2 retries."""
        max_retries = 2
        for attempt in range(max_retries + 1):
            try:
                if level in (AlertLevel.ERROR, AlertLevel.CRITICAL):
                    await self.bot.send_error_alert(styled_message)
                else:
                    await self.bot.send_message(styled_message)

                if dedup_key:
                    self.sent_alerts[dedup_key] = now
                return  # success

            except Exception as e:
                if attempt < max_retries:
                    wait_time = (attempt + 1) * 3
                    logger.warning("[ALERTS] Send failed (attempt %d): %s. Retrying in %ds...",
                                   attempt + 1, e, wait_time)
                    await asyncio.sleep(wait_time)
                else:
                    logger.error("[ALERTS] Persistent failure after %d retries: %s", max_retries, e)

    def _apply_style(self, message: str, level: AlertLevel) -> str:
        """Apply text prefixes based on level (plain text, no Markdown)."""
        prefixes = {
            AlertLevel.INFO: "[INFO] ",
            AlertLevel.WARNING: "[WARNING] ",
            AlertLevel.TRADE: "[TRADE] ",
            AlertLevel.ERROR: "[ERROR] ",
            AlertLevel.CRITICAL: "[CRITICAL] ",
        }
        prefix = prefixes.get(level, "")
        if level == AlertLevel.CRITICAL:
            return f"{prefix}{message}\n\nAccion requerida inmediata."
        return f"{prefix}{message}"

    def _persist_alert(self, message: str, level: AlertLevel, key: Optional[str]):
        """Append alert to data/alerts.jsonl for dashboard consumption."""
        alert_path = "data/alerts.jsonl"
        try:
            os.makedirs(os.path.dirname(alert_path), exist_ok=True)
            record = {
                "ts": datetime.now().isoformat(),
                "level": level.value,
                "msg": message,
                "key": key,
            }
            with open(alert_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record) + "\n")
        except Exception as e:
            logger.debug("[ALERTS] Failed to persist alert: %s", e)
