"""
Config validation — runs at bot startup.

Checks that all required env vars are present and that trading mode
flags are consistent. Fails fast with clear error messages.

Usage:
    from config.validation import validate_config
    validate_config()   # raises SystemExit on fatal errors
"""
import os
import sys
import logging

logger = logging.getLogger(__name__)


class ConfigError(Exception):
    """Raised when configuration is invalid and the bot cannot start."""
    pass


def _env(key: str, default=None) -> str | None:
    """Read an env var, stripping whitespace."""
    val = os.getenv(key, default)
    return val.strip() if val else val


def _is_true(val: str | None) -> bool:
    """Parse a boolean-ish env var."""
    return str(val).lower() in ("true", "1", "yes")


def validate_config():
    """
    Validate the bot configuration before startup.

    Checks:
      1. Required credentials are present
      2. Trading mode flags are consistent
      3. Risk parameters are within safe ranges
      4. Optional services are configured correctly

    Raises SystemExit with a clear message on fatal errors.
    Prints warnings for non-fatal inconsistencies.
    """
    errors: list[str] = []
    warnings: list[str] = []

    # ── 1. Exchange credentials ──────────────────────────────
    api_key = _env("BINANCE_API_KEY")
    api_secret = _env("BINANCE_API_SECRET") or _env("BINANCE_SECRET_KEY")

    if not api_key or api_key == "your_api_key_here":
        errors.append(
            "BINANCE_API_KEY is missing or still set to the placeholder.\n"
            "  → Get keys from https://testnet.binancefuture.com"
        )

    if not api_secret or api_secret == "your_api_secret_here":
        errors.append(
            "BINANCE_API_SECRET is missing or still set to the placeholder.\n"
            "  → Get keys from https://testnet.binancefuture.com"
        )

    # ── 2. Trading mode consistency ──────────────────────────
    trading_env = _env("TRADING_ENV", "TESTNET").upper()
    use_testnet = _is_true(_env("USE_TESTNET", "True"))
    analysis_only = _is_true(_env("ANALYSIS_ONLY", "False"))
    dry_run = _is_true(_env("DRY_RUN", "False"))

    valid_envs = {"SIM", "TESTNET", "DEMO", "LIVE"}
    if trading_env not in valid_envs:
        errors.append(
            f"TRADING_ENV='{trading_env}' is not valid.\n"
            f"  → Use one of: {', '.join(sorted(valid_envs))}"
        )

    if trading_env == "LIVE":
        if use_testnet:
            warnings.append(
                "TRADING_ENV=LIVE but USE_TESTNET=True.\n"
                "  → USE_TESTNET will be overridden to False for LIVE mode."
            )
        if analysis_only:
            warnings.append(
                "TRADING_ENV=LIVE but ANALYSIS_ONLY=True.\n"
                "  → The bot will NOT place real orders even in LIVE mode.\n"
                "  → Set ANALYSIS_ONLY=False if you intend to trade for real."
            )

    if dry_run and analysis_only:
        warnings.append(
            "Both DRY_RUN=True and ANALYSIS_ONLY=True are set.\n"
            "  → ANALYSIS_ONLY takes priority. DRY_RUN has no effect."
        )

    # ── 3. Risk parameters ───────────────────────────────────
    try:
        leverage = int(_env("MAX_LEVERAGE", "3") or "3")
        if leverage < 1:
            errors.append("MAX_LEVERAGE must be >= 1.")
        elif leverage > 125:
            errors.append(
                f"MAX_LEVERAGE={leverage} exceeds Binance maximum (125)."
            )
        elif leverage > 50:
            warnings.append(
                f"MAX_LEVERAGE={leverage} is very high. Consider <= 20."
            )
    except ValueError:
        errors.append("MAX_LEVERAGE must be an integer.")

    try:
        risk = float(_env("RISK_PER_TRADE", "0.01") or "0.01")
        if risk <= 0 or risk > 1:
            errors.append(
                f"RISK_PER_TRADE={risk} is out of range.\n"
                "  → Must be between 0 (exclusive) and 1 (inclusive).\n"
                "  → Recommended: 0.01 (1% of equity per trade)"
            )
        elif risk > 0.05:
            warnings.append(
                f"RISK_PER_TRADE={risk} ({risk*100:.0f}%) is aggressive.\n"
                "  → Recommended: <= 0.02 (2%) for safety."
            )
    except ValueError:
        errors.append("RISK_PER_TRADE must be a decimal number (e.g. 0.01).")

    try:
        daily_loss = float(_env("MAX_DAILY_LOSS", "0.05") or "0.05")
        if daily_loss <= 0 or daily_loss > 1:
            errors.append(
                f"MAX_DAILY_LOSS={daily_loss} is out of range (0, 1]."
            )
    except ValueError:
        errors.append("MAX_DAILY_LOSS must be a decimal number (e.g. 0.05).")

    # ── 4. Symbols ───────────────────────────────────────────
    symbols_raw = _env("SYMBOLS", "BTC/USDT,ETH/USDT")
    if not symbols_raw:
        errors.append("SYMBOLS is empty. At least one trading pair is required.")
    else:
        symbols = [s.strip() for s in symbols_raw.split(",") if s.strip()]
        if not symbols:
            errors.append("SYMBOLS contains no valid trading pairs.")
        for sym in symbols:
            if "/" not in sym:
                warnings.append(
                    f"Symbol '{sym}' does not contain '/'. Expected format: BTC/USDT"
                )

    # ── 5. Telegram (optional) ───────────────────────────────
    tg_enabled = _is_true(_env("TELEGRAM_ENABLED", "false"))
    tg_token = _env("TELEGRAM_TOKEN")
    tg_chat = _env("TELEGRAM_CHAT_ID")

    if tg_enabled:
        if not tg_token or tg_token == "your_bot_token_from_botfather":
            warnings.append(
                "TELEGRAM_ENABLED=true but TELEGRAM_TOKEN is missing/placeholder.\n"
                "  → Telegram notifications will be disabled."
            )
        if not tg_chat or tg_chat == "your_chat_id":
            warnings.append(
                "TELEGRAM_ENABLED=true but TELEGRAM_CHAT_ID is missing/placeholder.\n"
                "  → Telegram notifications will be disabled."
            )

    # ── 6. Polling interval ──────────────────────────────────
    try:
        interval = int(_env("POLLING_INTERVAL", "60") or "60")
        if interval < 10:
            warnings.append(
                f"POLLING_INTERVAL={interval}s is very short.\n"
                "  → May trigger rate limits on Binance. Recommended: >= 30."
            )
    except ValueError:
        errors.append("POLLING_INTERVAL must be an integer (seconds).")

    # ══════════════════════════════════════════════════════════
    #  Report results
    # ══════════════════════════════════════════════════════════
    if warnings:
        print("\n" + "=" * 60)
        print("  CONFIG WARNINGS")
        print("=" * 60)
        for i, w in enumerate(warnings, 1):
            print(f"\n  [{i}] {w}")
        print()
        for w in warnings:
            logger.warning("Config: %s", w.split("\n")[0])

    if errors:
        print("\n" + "=" * 60)
        print("  FATAL CONFIG ERRORS — Bot cannot start")
        print("=" * 60)
        for i, e in enumerate(errors, 1):
            print(f"\n  [{i}] {e}")
        print(f"\n  Fix these in your .env file and restart.")
        print("=" * 60 + "\n")
        sys.exit(1)

    # ── Summary ──────────────────────────────────────────────
    mode_desc = f"{trading_env}"
    if analysis_only:
        mode_desc += " (Analysis Only)"
    elif dry_run:
        mode_desc += " (Dry Run)"

    print(f"\n  [OK] Config validated: {mode_desc}")
    print(f"       Symbols: {symbols_raw}")
    print(f"       Leverage: {_env('MAX_LEVERAGE', '3')}x, "
          f"Risk/trade: {float(_env('RISK_PER_TRADE', '0.01') or 0.01)*100:.1f}%")
    print(f"       Telegram: {'ON' if tg_enabled else 'OFF'}\n")
    logger.info("Config validated: %s", mode_desc)
