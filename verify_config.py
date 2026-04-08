import os
import sys
from dotenv import load_dotenv

# Add current directory to path to import config
sys.path.append(os.getcwd())


def verify_config():
    print("--- Section 1.1: Configuration Verification ---")
    load_dotenv()

    from config.config_loader import Config

    critical_vars = [
        "BINANCE_API_KEY",
        "BINANCE_API_SECRET",
        "TELEGRAM_TOKEN",
        "TELEGRAM_CHAT_ID",
        "TRADING_ENV",
        "SYMBOLS",
    ]

    missing = []
    for var in critical_vars:
        val = os.getenv(var)
        status = "OK" if val else "MISSING"
        if not val:
            missing.append(var)

        # Obfuscate secrets for display
        display_val = val
        if val and ("KEY" in var or "SECRET" in var or "TOKEN" in var):
            display_val = val[:5] + "..." + val[-5:] if len(val) > 10 else "***"

        print(f"[{status}] {var}: {display_val}")

    print("\n--- Section 1.2: Mode Detection ---")
    print(f"TRADING_ENV: {Config.TRADING_ENV}")
    print(f"USE_TESTNET: {Config.USE_TESTNET}")
    print(f"PAPER_TRADING_ENABLED: {Config.PAPER_TRADING_ENABLED}")
    print(f"ANALYSIS_ONLY: {Config.ANALYSIS_ONLY}")
    print(f"SYMBOLS: {Config.SYMBOLS}")

    if missing:
        print(f"\nWARNING: Missing critical variables: {missing}")
    else:
        print("\nAll critical configuration variables are present.")


if __name__ == "__main__":
    verify_config()
