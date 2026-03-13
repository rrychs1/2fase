from prometheus_client import start_http_server, Counter, Gauge
import logging
from config.config_loader import Config

logger = logging.getLogger(__name__)

# --- Counters ---
bot_total_trades = Counter('bot_total_trades', 'Total number of closed trades')
bot_winning_trades = Counter('bot_winning_trades', 'Total number of winning trades')

# --- Gauges ---
bot_realized_pnl = Gauge('bot_realized_pnl', 'Total realized PnL in USD')
bot_unrealized_pnl = Gauge('bot_unrealized_pnl', 'Total unrealized PnL in USD')
bot_daily_drawdown_pct = Gauge('bot_daily_drawdown_pct', 'Current daily drawdown percentage (negative value)')
bot_current_exposure = Gauge('bot_current_exposure', 'Total notional exposure currently open in USD')

# --- System Health ---
bot_system_health = Gauge('bot_system_health', 'Global system health (1=OK, 0=KillSwitch Triggered / Safe Mode)')
bot_ws_connected = Gauge('bot_ws_connected', 'Websocket connection status (1=Connected, 0=Disconnected)')

def start_metrics_exporter():
    if getattr(Config, 'ENABLE_METRICS', True):
        port = getattr(Config, 'METRICS_PORT', 8000)
        try:
            start_http_server(port)
            logger.info(f"📊 Prometheus Metrics Exporter started on http://localhost:{port}/metrics")
        except Exception as e:
            logger.error(f"Failed to start Metrics Exporter on port {port}: {e}")
