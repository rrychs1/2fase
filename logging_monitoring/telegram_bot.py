"""
Telegram Bot wrapper — safe import, never raises, respects .env flags.

If python-telegram-bot is not installed or TELEGRAM_ENABLED=false,
all methods become silent no-ops.
"""
import os
import time
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

# ── Safe import of python-telegram-bot ────────────────────────
# The import is guarded so the bot can run even if the package
# is missing (e.g. in a minimal Docker image or test env).
try:
    from telegram import Bot as _TelegramBot
    from telegram.error import TelegramError
    _HAS_TELEGRAM = True
except ImportError:
    _TelegramBot = None
    TelegramError = Exception  # fallback for except clauses
    _HAS_TELEGRAM = False
    logger.info("python-telegram-bot not installed. Telegram disabled.")


class TelegramBot:
    """
    Thin wrapper around python-telegram-bot.

    Controlled by .env:
      TELEGRAM_ENABLED=true/false  (master switch)
      TELEGRAM_TOKEN=...
      TELEGRAM_CHAT_ID=...

    If disabled or misconfigured, every method is a silent no-op.
    Exceptions are caught and logged — never propagated to the caller.
    """

    def __init__(self):
        self.token = os.getenv("TELEGRAM_TOKEN", "").strip()
        self.chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()

        # Master switch
        explicitly_disabled = os.getenv("TELEGRAM_ENABLED", "true").lower() in ("false", "0", "no")

        # Enabled only if: package available + not disabled + credentials present
        self.enabled = (
            _HAS_TELEGRAM
            and not explicitly_disabled
            and bool(self.token)
            and bool(self.chat_id)
            and self.token != "your_bot_token_from_botfather"
            and self.chat_id != "your_chat_id"
        )

        self.bot = _TelegramBot(token=self.token) if self.enabled else None

        # Health tracking
        self.consecutive_failures = 0
        self.max_failures = 3
        self.last_failure_ts = 0.0
        self.health_retry_window = 300  # 5 minutes

        if self.enabled:
            logger.info("Telegram notifications enabled.")
        else:
            reason = "disabled"
            if not _HAS_TELEGRAM:
                reason = "python-telegram-bot not installed"
            elif explicitly_disabled:
                reason = "TELEGRAM_ENABLED=false"
            elif not self.token or self.token == "your_bot_token_from_botfather":
                reason = "TELEGRAM_TOKEN missing or placeholder"
            elif not self.chat_id or self.chat_id == "your_chat_id":
                reason = "TELEGRAM_CHAT_ID missing or placeholder"
            logger.info("Telegram notifications disabled (%s).", reason)

    # ── Public API (all methods are safe — never raise) ──────

    async def verify_bot(self) -> str | None:
        """Verify bot token and log identity. Returns username or None."""
        if not self.enabled:
            return None
        try:
            me = await self.bot.get_me()
            logger.info("Telegram Bot Connected: @%s (ID: %s)", me.username, me.id)
            return me.username
        except Exception as e:
            logger.warning("Failed to verify Telegram Bot: %s", e)
            self._record_failure()
            return None

    async def send_message(self, message: str) -> bool:
        """Send a plain text message. Returns True on success."""
        if not self.enabled:
            return False
        try:
            await self.bot.send_message(chat_id=self.chat_id, text=message)
            self.consecutive_failures = 0
            return True
        except Exception as e:
            self._record_failure()
            logger.warning("Telegram send failed: %s (failures: %d)", e, self.consecutive_failures)
            return False

    async def send_trade_alert(self, symbol: str, side: str, price: float,
                               amount: float, strategy: str) -> bool:
        """Send a formatted trade alert. Returns True on success."""
        if not self.enabled:
            return False

        emoji = "BUY" if side.lower() == "buy" else "SELL"
        msg = (
            f"[{emoji}] TRADE ALERT\n\n"
            f"Par: {symbol}\n"
            f"Side: {side}\n"
            f"Precio: {price:.2f}\n"
            f"Cantidad: {amount:.4f}\n"
            f"Estrategia: {strategy}\n"
            f"Hora: {datetime.now().strftime('%H:%M:%S')}"
        )
        return await self.send_message(msg)

    async def send_error_alert(self, error_msg: str) -> bool:
        """Send a critical error alert. Returns True on success."""
        if not self.enabled:
            return False
        msg = f"[!] CRITICAL ERROR\n\n{error_msg}"
        return await self.send_message(msg)

    async def send_status_update(self, equity: float, pnl: float) -> bool:
        """Send a periodic status update. Returns True on success."""
        if not self.enabled:
            return False
        direction = "UP" if pnl >= 0 else "DOWN"
        msg = (
            f"STATUS UPDATE\n"
            f"Equity: {equity:.2f} USDT\n"
            f"PnL Hoy: {pnl:.2f} USDT ({direction})"
        )
        return await self.send_message(msg)

    def is_healthy(self) -> bool:
        """Check if the alert channel is functioning."""
        if not self.enabled:
            return False
        if self.consecutive_failures < self.max_failures:
            return True
        # If too many failures, allow a retry every health_retry_window
        if time.time() - self.last_failure_ts > self.health_retry_window:
            logger.info("[TELEGRAM] Health retry window reached. Allowing attempt.")
            return True
        return False

    async def close(self):
        """Close the underlying bot session."""
        if self.bot is not None:
            try:
                # python-telegram-bot async Bot has a shutdown/close mechanism if used with application, 
                # but if used raw, we should close the networking client if it exists.
                if hasattr(self.bot, 'shutdown'):
                    await self.bot.shutdown()
                elif hasattr(self.bot, 'close'):
                    await self.bot.close()
                elif hasattr(self.bot, '_request') and hasattr(self.bot._request, 'stop'):
                    await self.bot._request.stop()
            except Exception as e:
                logger.debug("Error closing Telegram bot: %s", e)

    # ── Internal ─────────────────────────────────────────────

    def _record_failure(self):
        self.consecutive_failures += 1
        self.last_failure_ts = time.time()
