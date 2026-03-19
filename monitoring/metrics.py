from prometheus_client import start_http_server, Counter, Gauge, Histogram
import logging
from config.config_loader import Config

logger = logging.getLogger(__name__)

# --- High-Frequency Execution Timing ---
execution_latency_ms = Histogram(
    'execution_latency_ms', 
    'Time taken to natively execute an exchange order in ms',
    buckets=(10, 50, 100, 250, 500, 1000, 2500, 5000)
)

# --- Slippage Monitoring ---
order_slippage_bps = Histogram(
    'order_slippage_bps', 
    'Slippage incurred per filled order in basis points (bps)',
    buckets=(1, 5, 10, 20, 50, 100)
)

# --- Statistical Rolling Metrics ---
rolling_win_rate_pct = Gauge(
    'rolling_win_rate_pct',
    'Current win rate percentage over the trading horizon natively'
)

# Inherit baseline counters to replace `metrics_server.py`
bot_total_trades = Counter('bot_total_trades', 'Total number of closed trades')
bot_winning_trades = Counter('bot_winning_trades', 'Total number of winning trades')
bot_realized_pnl = Gauge('bot_realized_pnl', 'Total realized PnL in USD')
bot_unrealized_pnl = Gauge('bot_unrealized_pnl', 'Total unrealized PnL in USD')
bot_daily_drawdown_pct = Gauge('bot_daily_drawdown_pct', 'Current daily drawdown percentage (negative value)')
bot_current_exposure = Gauge('bot_current_exposure', 'Total notional exposure currently open in USD')
bot_system_health = Gauge('bot_system_health', 'Global system health (1=OK, 0=KillSwitch Triggered / Safe Mode)')
bot_ws_connected = Gauge('bot_ws_connected', 'Websocket connection status (1=Connected, 0=Disconnected)')


def start_metrics_exporter():
    """
    Idempotent prometheus endpoint startup structurally serving standard metrics.
    """
    if getattr(Config, 'ENABLE_METRICS', True):
        port = getattr(Config, 'METRICS_PORT', 8000)
        try:
            start_http_server(port)
            logger.info("Prometheus Extended Metrics Exporter active", extra={"event": "SystemStartup", "symbol": "SYSTEM", "port": port})
        except Exception as e:
            logger.error(f"Failed to start Metrics Exporter: {e}", extra={"event": "SystemError", "symbol": "SYSTEM"})
