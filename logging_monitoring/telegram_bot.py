
import os
import logging
import asyncio
from telegram import Bot
from telegram.error import TelegramError
from datetime import datetime

logger = logging.getLogger(__name__)

class TelegramBot:
    def __init__(self):
        self.token = os.getenv('TELEGRAM_TOKEN')
        self.chat_id = os.getenv('TELEGRAM_CHAT_ID')
        self.enabled = bool(self.token and self.chat_id)
        self.bot = Bot(token=self.token) if self.enabled else None
        
        self.consecutive_failures = 0
        self.max_failures = 3
        
        if not self.enabled:
            logger.warning("Telegram configuration missing. Notifications disabled.")
        else:
            logger.info("Telegram notifications enabled.")

    async def verify_bot(self):
        """Verify bot token and log identity."""
        if not self.enabled: return
        try:
            me = await self.bot.get_me()
            logger.info(f"Telegram Bot Connected: @{me.username} (ID: {me.id})")
            return me.username
        except Exception as e:
            logger.error(f"Failed to verify Telegram Bot: {e}")

    async def send_message(self, message: str):
        """Send a generic message to the configured chat."""
        if not self.enabled: return
        
        try:
            await self.bot.send_message(chat_id=self.chat_id, text=message)
            self.consecutive_failures = 0 # Reset on success
        except TelegramError as e:
            self.consecutive_failures += 1
            logger.error(f"Failed to send Telegram message: {e} (failures: {self.consecutive_failures})")

    def is_healthy(self) -> bool:
        """Check if the alert channel is functioning."""
        if not self.enabled: return False
        return self.consecutive_failures < self.max_failures

    async def send_trade_alert(self, symbol: str, side: str, price: float, amount: float, strategy: str):
        """Send a formatted trade alert."""
        if not self.enabled: return

        emoji = "🟢" if side.lower() == "buy" else "🔴"
        action = "COMPRA" if side.lower() == "buy" else "VENTA"
        
        msg = (
            f"{emoji} **TRADING ALERT** {emoji}\n\n"
            f"**Par:** {symbol}\n"
            f"**Acción:** {action}\n"
            f"**Precio:** {price:.2f}\n"
            f"**Cantidad:** {amount:.4f}\n"
            f"**Estrategia:** {strategy}\n"
            f"**Hora:** {datetime.now().strftime('%H:%M:%S')}"
        )
        # Markdown parsing can be tricky with special chars, using plain text or basic HTML might be safer if not escaping.
        # For simplicity, we'll try sending as standard text first or minimal markdown.
        try:
           await self.bot.send_message(chat_id=self.chat_id, text=msg, parse_mode='Markdown')
        except TelegramError:
            # Fallback to plain text if markdown fails
            await self.bot.send_message(chat_id=self.chat_id, text=msg.replace('*', ''))

    async def send_error_alert(self, error_msg: str):
        """Send a critical error alert."""
        if not self.enabled: return
        
        msg = f"🚨 **CRITICAL ERROR** 🚨\n\n{error_msg}"
        try:
            await self.bot.send_message(chat_id=self.chat_id, text=msg, parse_mode='Markdown')
        except TelegramError:
            await self.bot.send_message(chat_id=self.chat_id, text=msg.replace('*', ''))

    async def send_status_update(self, equity: float, pnl: float):
        """Send a periodic status update."""
        if not self.enabled: return
        
        emoji = "📈" if pnl >= 0 else "📉"
        msg = (
            f"ℹ️ **STATUS UPDATE**\n"
            f"**Equity:** {equity:.2f} USDT\n"
            f"**PnL Hoy:** {pnl:.2f} USDT {emoji}"
        )
        await self.send_message(msg)
