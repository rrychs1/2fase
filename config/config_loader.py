import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    # --- Exchange Credentials ---
    BINANCE_API_KEY = os.getenv('BINANCE_API_KEY')
    # Support both 'BINANCE_API_SECRET' (new) and 'BINANCE_SECRET_KEY' (legacy)
    BINANCE_SECRET_KEY = os.getenv('BINANCE_API_SECRET') or os.getenv('BINANCE_SECRET_KEY')
    
    # --- Environment & Mode ---
    # TRADING_ENV: SIM, TESTNET, LIVE
    TRADING_ENV = os.getenv('TRADING_ENV', 'TESTNET').upper()
    # Support legacy USE_TESTNET flag
    USE_TESTNET = TRADING_ENV in ['TESTNET', 'DEMO'] or os.getenv('USE_TESTNET', 'True').lower() == 'true'
    
    # Senior Audit Phase 17: Explicit flag for Paper Trading logic
    PAPER_TRADING_ENABLED = os.getenv('PAPER_TRADING_ENABLED', 'True').lower() == 'true'
    
    # Modo solo análisis: evita órdenes/apalancamiento hasta validar credenciales
    ANALYSIS_ONLY = os.getenv('ANALYSIS_ONLY', 'False').lower() == 'true'
    DRY_RUN = os.getenv('DRY_RUN', 'False').lower() == 'true'
    
    # NEW: Unified Execution Mode: LIVE, PAPER, or SHADOW
    _legacy_mode = 'PAPER' if ANALYSIS_ONLY else ('SHADOW' if DRY_RUN else 'LIVE')
    EXECUTION_MODE = os.getenv('EXECUTION_MODE', _legacy_mode).upper()

    # Websocket Settings
    USE_WEBSOCKETS = os.getenv('USE_WEBSOCKETS', 'True').lower() == 'true'
    WS_MAX_RETRIES = int(os.getenv('WS_MAX_RETRIES', '5'))
    WS_HEARTBEAT_TIMEOUT = int(os.getenv('WS_HEARTBEAT_TIMEOUT', '60'))

    SYMBOLS = os.getenv('SYMBOLS', 'BTC/USDT,ETH/USDT').split(',')
    
    # --- Risk Parameters ---
    LEVERAGE = int(os.getenv('MAX_LEVERAGE') or os.getenv('LEVERAGE') or 3)
    MAX_RISK_PER_TRADE = float(os.getenv('MAX_RISK_PER_TRADE', '0.05'))
    DAILY_LOSS_LIMIT = float(os.getenv('DAILY_LOSS_LIMIT', '0.10'))
    MAX_INVENTORY_RATIO = float(os.getenv('MAX_INVENTORY_RATIO', '0.15'))
    MAX_TOTAL_EXPOSURE = float(os.getenv('MAX_TOTAL_EXPOSURE', '0.50'))
    
    # Prometheus Metrics
    ENABLE_METRICS = os.getenv("ENABLE_METRICS", "True").lower() == "true"
    METRICS_PORT = int(os.getenv("METRICS_PORT", 8000)) 
    # Liquidity Limits
    MAX_ORDER_DEPTH_RATIO = float(os.getenv('MAX_ORDER_DEPTH_RATIO', '0.10'))
    LIQUIDITY_HAIRCUT = float(os.getenv('LIQUIDITY_HAIRCUT', '0.20'))
    MAX_SPREAD_PCT = float(os.getenv('MAX_SPREAD_PCT', '0.005'))
    MAX_SLIPPAGE_PCT = float(os.getenv('MAX_SLIPPAGE_PCT', '0.002'))
    
    # Grid Strategy Settings
    GRID_LEVELS = int(os.getenv('GRID_LEVELS', '5')) # Initial legacy level count
    GRID_MAX_LEVELS = int(os.getenv('GRID_MAX_LEVELS', '20')) # Prevent excessive orders in low vol
    GRID_ATR_MULTIPLIER = float(os.getenv('GRID_ATR_MULTIPLIER', '0.5')) # Base multiplier 'k' para grid_spacing = k * ATR
    
    KILL_SWITCH_ENABLED = os.getenv('KILL_SWITCH_ENABLED', 'True').lower() == 'true'
    COOLDOWN_MINUTES = float(os.getenv('COOLDOWN_MINUTES', 5.0))
    MIN_NOTIONAL = float(os.getenv('MIN_NOTIONAL', 100.0))  # Testnet often requires 100+
    MAX_PRICE_DEVIATION_PCT = float(os.getenv('MAX_PRICE_DEVIATION_PCT', 0.05))

    # --- Operational ---
    POLLING_INTERVAL = int(os.getenv('POLLING_INTERVAL', 60))
    CANDLES_ANALYSIS_LIMIT = int(os.getenv('CANDLES_ANALYSIS_LIMIT', 200))

    # Timeframes
    TF_GRID = os.getenv('TF_GRID', '4h')
    TF_TREND = os.getenv('TF_TREND', '1h')
    
    # Strategy Parameters
    GRID_LEVELS = 5
    DCA_STEPS = 3
    ATR_PERIOD = 14

    # --- Optional Services ---
    TELEGRAM_ENABLED = os.getenv('TELEGRAM_ENABLED', 'true').lower() == 'true'
    DASHBOARD_ENABLED = os.getenv('DASHBOARD_ENABLED', 'true').lower() == 'true'
    DASHBOARD_PORT = int(os.getenv('DASHBOARD_PORT', 8000))
