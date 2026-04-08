"""
Bot Startup Pipeline — validates everything BEFORE the main loop starts.

Pipeline stages:
  1. Environment    — venv check
  2. Syntax         — compile all .py files
  3. Dependencies   — verify all required packages
  4. Configuration  — validate .env variables
  5. Services       — ping Telegram + Exchange APIs
  6. Launch         — hand off to BotRunner

If any stage fails, the bot logs a clear error and exits safely.
"""

import sys
import os
import importlib.util

# ═══════════════════════════════════════════════════════════════
#  Helpers
# ═══════════════════════════════════════════════════════════════

_STAGE = 0


def _stage(name: str):
    """Print and track the current pipeline stage."""
    global _STAGE
    _STAGE += 1
    print(f"\n  [{_STAGE}/6] {name}...")
    sys.stdout.flush()


def _fail(message: str):
    """Print a fatal error and exit."""
    sys.stdout.flush()
    print(f"\n  FAILED at stage {_STAGE}:", file=sys.stderr)
    print(f"  {message}", file=sys.stderr)
    sys.stderr.flush()
    sys.exit(1)


def _ok(detail: str = ""):
    """Print a stage success marker."""
    suffix = f" - {detail}" if detail else ""
    print(f"        OK{suffix}")


# ═══════════════════════════════════════════════════════════════
#  Stage 1: Virtual Environment
# ═══════════════════════════════════════════════════════════════


def stage_environment():
    _stage("Validating Python environment")

    in_venv = hasattr(sys, "real_prefix") or (
        hasattr(sys, "base_prefix") and sys.base_prefix != sys.prefix
    )
    in_conda = "CONDA_PREFIX" in os.environ

    if not (in_venv or in_conda):
        print(
            "  CRITICAL: Running outside a virtual environment (PEP 668).\n",
            file=sys.stderr,
        )
        print("  Quick fix:", file=sys.stderr)
        print("    python -m venv venv", file=sys.stderr)
        print(
            "    source venv/bin/activate  # Windows: venv\\Scripts\\activate",
            file=sys.stderr,
        )
        print("    pip install -r requirements.txt", file=sys.stderr)
        print("    python main.py", file=sys.stderr)
        _fail("Virtual environment required.")

    _ok(f"Python {sys.version.split()[0]}")


# ═══════════════════════════════════════════════════════════════
#  Stage 2: Syntax Validation
# ═══════════════════════════════════════════════════════════════


def stage_syntax():
    _stage("Checking syntax across codebase")
    import py_compile

    root_dir = os.path.dirname(os.path.abspath(__file__))
    errors = []
    file_count = 0

    for dirpath, dirnames, filenames in os.walk(root_dir):
        # Skip non-project directories
        dirnames[:] = [
            d
            for d in dirnames
            if d not in ("venv", ".git", "__pycache__", ".pytest_cache", "node_modules")
        ]
        for filename in filenames:
            if filename.endswith(".py"):
                filepath = os.path.join(dirpath, filename)
                file_count += 1
                try:
                    py_compile.compile(filepath, doraise=True)
                except py_compile.PyCompileError as e:
                    errors.append(str(e))

    if errors:
        for err in errors:
            print(f"  ERROR: {err}", file=sys.stderr)
        _fail(f"{len(errors)} syntax error(s) found in {file_count} files.")

    _ok(f"{file_count} files clean")


# ═══════════════════════════════════════════════════════════════
#  Stage 3: Dependencies
# ═══════════════════════════════════════════════════════════════

REQUIRED_PACKAGES = {
    "aiohttp": "aiohttp",
    "ccxt": "ccxt",
    "dotenv": "python-dotenv",
    "flask": "flask",
    "matplotlib": "matplotlib",
    "numpy": "numpy",
    "pandas": "pandas",
    "prometheus_client": "prometheus_client",
    "psutil": "psutil",
    "requests": "requests",
    "scipy": "scipy",
    "ta": "ta",
    "telegram": "python-telegram-bot",
    "websockets": "websockets",
}


def stage_dependencies():
    _stage("Verifying installed packages")

    missing = []
    for module_name, pip_name in REQUIRED_PACKAGES.items():
        if importlib.util.find_spec(module_name) is None:
            missing.append(pip_name)

    if missing:
        print(f"  Missing: {', '.join(missing)}", file=sys.stderr)
        print(f"\n  Fix:  pip install {' '.join(missing)}", file=sys.stderr)
        _fail(f"{len(missing)} package(s) not installed.")

    _ok(f"{len(REQUIRED_PACKAGES)} packages verified")


# ═══════════════════════════════════════════════════════════════
#  Stage 4: Configuration (.env)
# ═══════════════════════════════════════════════════════════════


def stage_configuration():
    _stage("Validating configuration")
    from dotenv import load_dotenv

    load_dotenv()

    from config.validation import validate_config

    # validate_config() calls sys.exit(1) on fatal errors,
    # printing full details to stdout/stderr.
    validate_config()
    _ok()


# ═══════════════════════════════════════════════════════════════
#  Stage 5: External Services (Telegram + Exchange)
# ═══════════════════════════════════════════════════════════════


def stage_services():
    import asyncio

    _stage("Verifying external services")

    async def _verify():
        results = []

        # ── Telegram ─────────────────────────────────────────
        from logging_monitoring.telegram_alert_service import TelegramAlertService

        alerts = TelegramAlertService()
        if alerts.enabled:
            username = await alerts.verify_bot()
            if not username:
                _fail(
                    "Telegram is enabled but API verification failed.\n"
                    "  Check TELEGRAM_TOKEN and network connectivity."
                )
            await alerts.info("✅ Startup pipeline: Telegram verified.", force=True)
            await alerts.close()
            results.append(f"Telegram @{username}")
        else:
            results.append("Telegram disabled")

        # ── Exchange ─────────────────────────────────────────
        from exchange.exchange_client import ExchangeClient
        from config.config_loader import Config

        if Config.TRADING_ENV != "SIM":
            exchange = ExchangeClient()
            try:
                balance = await exchange.fetch_balance()
                equity = balance.get("total", {}).get("USDT", 0.0)
                if equity <= 0 and not Config.ANALYSIS_ONLY:
                    print(
                        "  WARNING: Exchange returned 0 equity. "
                        "Continuing in read-only mode.",
                        file=sys.stderr,
                    )
                results.append(f"Exchange equity: {equity:.2f} USDT")
            except Exception as e:
                if Config.ANALYSIS_ONLY:
                    results.append(f"Exchange unreachable (analysis-only, continuing)")
                else:
                    _fail(
                        f"Exchange connection failed: {e}\n"
                        "  Verify BINANCE_API_KEY/SECRET and network."
                    )
            finally:
                await exchange.close()
        else:
            results.append("Exchange skipped (SIM mode)")

        _ok(" | ".join(results))

    asyncio.run(_verify())


# ═══════════════════════════════════════════════════════════════
#  Stage 6: Launch
# ═══════════════════════════════════════════════════════════════


def stage_launch():
    import asyncio

    _stage("Launching bot")
    print()

    from orchestration.bot_runner import BotRunner

    runner = BotRunner()
    try:
        asyncio.run(runner.run())
    except KeyboardInterrupt:
        print("\nBot stopped by user.")


# ═══════════════════════════════════════════════════════════════
#  Pipeline
# ═══════════════════════════════════════════════════════════════

PIPELINE = [
    stage_environment,
    stage_syntax,
    stage_dependencies,
    stage_configuration,
    stage_services,
    stage_launch,
]


def run_pipeline():
    print("\n  +==========================================+")
    print("  |       Bot Startup Pipeline               |")
    print("  +==========================================+")

    for stage_fn in PIPELINE:
        stage_fn()


if __name__ == "__main__":
    run_pipeline()
