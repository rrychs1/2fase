import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    BINANCE_API_KEY = os.getenv('BINANCE_API_KEY')
    BINANCE_SECRET_KEY = os.getenv('BINANCE_SECRET_KEY')
    USE_TESTNET = os.getenv('USE_TESTNET', 'True').lower() == 'true'
    # Modo solo análisis: evita órdenes/apalancamiento hasta validar credenciales de Futuros
    ANALYSIS_ONLY = os.getenv('ANALYSIS_ONLY', 'True').lower() == 'true'
    SYMBOLS = os.getenv('SYMBOLS', 'BTC/USDT,ETH/USDT').split(',')
    LEVERAGE = int(os.getenv('LEVERAGE', 3))
    MAX_RISK_PER_TRADE = float(os.getenv('MAX_RISK_PER_TRADE', 0.01))
    DAILY_LOSS_LIMIT = float(os.getenv('DAILY_LOSS_LIMIT', 0.02))
    POLLING_INTERVAL = int(os.getenv('POLLING_INTERVAL', 60))

    # Timeframes
    TF_GRID = os.getenv('TF_GRID', '4h')
    TF_TREND =os.getenv('TF_TREND', '1h')
    
    # Strategy Parameters
    GRID_LEVELS = 5
    DCA_STEPS = 3
    ATR_PERIOD = 14
