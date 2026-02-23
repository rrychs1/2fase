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
    
    # Modo solo análisis: evita órdenes/apalancamiento hasta validar credenciales
    ANALYSIS_ONLY = os.getenv('ANALYSIS_ONLY', 'False').lower() == 'true'
    DRY_RUN = os.getenv('DRY_RUN', 'False').lower() == 'true'
    SYMBOLS = os.getenv('SYMBOLS', 'BTC/USDT,ETH/USDT').split(',')
    
    # --- Risk Parameters ---
    LEVERAGE = int(os.getenv('MAX_LEVERAGE') or os.getenv('LEVERAGE') or 3)
    MAX_RISK_PER_TRADE = float(os.getenv('RISK_PER_TRADE') or os.getenv('MAX_RISK_PER_TRADE') or 0.01)
    DAILY_LOSS_LIMIT = float(os.getenv('MAX_DAILY_LOSS') or os.getenv('DAILY_LOSS_LIMIT') or 0.05)
    
    KILL_SWITCH_ENABLED = os.getenv('KILL_SWITCH_ENABLED', 'True').lower() == 'true'
    COOLDOWN_MINUTES = float(os.getenv('COOLDOWN_MINUTES', 5.0))
    MIN_NOTIONAL_USD = float(os.getenv('MIN_NOTIONAL_USD', 5.1))
    
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
