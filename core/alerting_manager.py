import asyncio
import logging
import json
import time
import hashlib
import os
import aiohttp
import smtplib
from email.mime.text import MIMEText
from datetime import datetime
from typing import Dict, Any, Optional, List

logger = logging.getLogger(__name__)

class AlertManager:
    """
    Production-grade alerting system with deduplication, cooldowns, and async dispatch.
    """
    
    def __init__(self, history_file: str = "logs/alert_history.jsonl"):
        self.history_file = history_file
        self.last_alerts: Dict[str, Dict[str, Any]] = {}  # {alert_hash: {time: timestamp, count: int}}
        self.cooldown_windows = {
            "INFO": 3600,      # 1 hour
            "WARNING": 1800,   # 30 minutes
            "CRITICAL": 300    # 5 minutes
        }
        
        # Ensure logs directory exists
        os.makedirs(os.path.dirname(history_file), exist_ok=True)
        
        # Webhook / Email config
        self.discord_webhook = os.getenv("DISCORD_WEBHOOK_URL")
        self.telegram_webhook = os.getenv("TELEGRAM_WEBHOOK_URL")
        self.email_config = {
            "smtp_server": os.getenv("SMTP_SERVER"),
            "smtp_port": int(os.getenv("SMTP_PORT", 587)),
            "sender": os.getenv("SMTP_SENDER"),
            "password": os.getenv("SMTP_PASSWORD"),
            "recipient": os.getenv("ALERT_RECIPIENT_EMAIL")
        }
        self._session: Optional[aiohttp.ClientSession] = None
        self._pending_tasks: List[asyncio.Task] = []
        
    async def _get_session(self) -> aiohttp.ClientSession:
        if not self._session or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self):
        """Clean up resources and await pending tasks."""
        if self._pending_tasks:
            # Filter out finished tasks
            unfinished = [t for t in self._pending_tasks if not t.done()]
            if unfinished:
                await asyncio.gather(*unfinished, return_exceptions=True)
            self._pending_tasks = []
            
        if self._session:
            await self._session.close()

    def _generate_hash(self, strategy_id: str, message: str, severity: str) -> str:
        """Generates a unique hash for an alert to deduplicate it."""
        content = f"{strategy_id}:{severity}:{message}"
        return hashlib.md5(content.encode()).hexdigest()

    def should_alert(self, alert_hash: str, severity: str) -> bool:
        """Determines if an alert should be dispatched based on cooldowns and state."""
        current_time = time.time()
        cooldown = self.cooldown_windows.get(severity, 3600)
        
        if alert_hash in self.last_alerts:
            last_time = self.last_alerts[alert_hash]["time"]
            if current_time - last_time < cooldown:
                return False
                
        return True

    async def send_alert(self, strategy_id: str, message: str, severity: str = "WARNING", metadata: Optional[Dict] = None):
        """Main entry point to dispatch an alert asynchronously."""
        alert_hash = self._generate_hash(strategy_id, message, severity)
        
        if not self.should_alert(alert_hash, severity):
            logger.debug(f"Alert dampened by cooldown: {strategy_id} - {message}")
            return

        # Update state
        self.last_alerts[alert_hash] = {
            "time": time.time(),
            "last_message": message
        }

        # Create alert payload
        payload = {
            "timestamp": datetime.now().isoformat(),
            "strategy_id": strategy_id,
            "severity": severity,
            "message": message,
            "metadata": metadata or {}
        }

        # 1. Persist to history file
        self._persist_alert(payload)

        # 2. Local logs
        log_level = getattr(logging, severity, logging.INFO)
        logger.log(log_level, f"ALERT [{severity}] {strategy_id}: {message}")

        # 3. Async dispatch to channels
        tasks = []
        if self.discord_webhook:
            tasks.append(self._dispatch_webhook(self.discord_webhook, payload))
        if self.telegram_webhook:
            tasks.append(self._dispatch_webhook(self.telegram_webhook, payload))
        if self.email_config["smtp_server"]:
            tasks.append(self._dispatch_email(payload))
            
        if tasks:
            async def dispatch_all(coros: List):
                await asyncio.gather(*coros, return_exceptions=True)
            
            task = asyncio.create_task(dispatch_all(tasks))
            self._pending_tasks.append(task)
            # Remove from list when done to avoid memory growth
            task.add_done_callback(lambda t: self._pending_tasks.remove(t) if t in self._pending_tasks else None)

    def _persist_alert(self, payload: Dict):
        """Appends alert to a JSONL log file for auditing."""
        try:
            with open(self.history_file, "a") as f:
                f.write(json.dumps(payload) + "\n")
        except Exception as e:
            logger.error(f"Failed to persist alert to {self.history_file}: {e}")

    async def _dispatch_webhook(self, url: str, payload: Dict):
        """Dispatches alert to a webhook endpoint."""
        try:
            # Format message for Discord/Telegram
            content = f"**[{payload['severity']}]** {payload['strategy_id']}\n{payload['message']}"
            if payload['metadata']:
                content += f"\n```json\n{json.dumps(payload['metadata'], indent=2)}\n```"
                
            session = await self._get_session()
            async with session.post(url, json={"content": content}) as response:
                if response.status >= 400:
                    logger.error(f"Webhook dispatch failed with status {response.status}")
        except Exception as e:
            logger.error(f"Webhook dispatch exception: {e}")

    async def _dispatch_email(self, payload: Dict):
        """Dispatches alert via email SMTP."""
        cfg = self.email_config
        if not cfg["smtp_server"] or not cfg["sender"] or not cfg["recipient"]:
            return

        try:
            msg = MIMEText(f"Severity: {payload['severity']}\nStrategy: {payload['strategy_id']}\nMessage: {payload['message']}\nMetadata: {json.dumps(payload['metadata'], indent=2)}")
            msg['Subject'] = str(f"TRADING BOT ALERT: {payload['severity']} - {payload['strategy_id']}")
            msg['From'] = str(cfg["sender"])
            msg['To'] = str(cfg["recipient"])

            # Run SMTP in thread to avoid blocking loop (smtplib is blocking)
            await asyncio.to_thread(self._send_smtp, msg, cfg)
        except Exception as e:
            logger.error(f"Email dispatch exception: {e}")

    def _send_smtp(self, msg: Any, cfg: Dict[str, Any]):
        """Blocking SMTP send logic."""
        server_name = str(cfg["smtp_server"])
        port = int(cfg["smtp_port"])
        with smtplib.SMTP(server_name, port) as server:
            server.starttls()
            server.login(str(cfg["sender"]), str(cfg["password"]))
            server.send_message(msg)
