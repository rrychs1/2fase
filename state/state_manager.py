"""
State Manager — Centralized read/write of bot state files.

Provides atomic writes (write-to-temp-then-rename) to avoid partial reads
by the dashboard, and a robust reader that never raises on corrupt files.
"""
import json
import os
import tempfile
import logging
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

# ── Canonical state schema (every field always present) ──────

STATE_DEFAULTS = {
    "running": False,
    "mode": "Unknown",
    "iteration": 0,
    "equity": 0.0,
    "balance": 0.0,
    "unrealized_pnl": 0.0,
    "open_positions": {},
    "pending_orders": [],
    "regimes": {},
    "prices": {},
    "history": [],
    "global_stats": {},
    "metrics": {},
    "status": {},
    "exchange_status": "Unknown",
    "telegram_healthy": False,
    "last_error": None,
    "uptime": "--",
    "timestamp": None,
}


def write_bot_state(path: str, state: dict) -> None:
    """
    Atomically write the bot state to a JSON file.

    Uses write-to-temp + os.replace so the dashboard never reads
    a half-written file.  On Windows os.replace is atomic within
    the same volume.
    """
    abs_path = os.path.abspath(path)
    target_dir = os.path.dirname(abs_path)

    # Ensure directory exists
    if target_dir and not os.path.exists(target_dir):
        os.makedirs(target_dir, exist_ok=True)

    # Inject timestamp if the caller didn't
    if "timestamp" not in state or state["timestamp"] is None:
        state["timestamp"] = datetime.now().isoformat()

    try:
        # Write to a temp file in the same directory, then rename
        fd, tmp_path = tempfile.mkstemp(
            suffix=".tmp", prefix=".state_", dir=target_dir
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(state, f, indent=2, default=str)
            os.replace(tmp_path, abs_path)
        except Exception:
            # Clean up the temp file on failure
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
            raise
    except Exception as e:
        logger.error(f"[StateManager] Failed to write state to {abs_path}: {e}")


def load_bot_state(path: str) -> Optional[dict]:
    """
    Load and validate the bot state file.

    Returns:
        dict  — the parsed state merged with defaults (every key guaranteed)
        None  — if the file is missing, empty, or corrupt
    """
    abs_path = os.path.abspath(path)

    if not os.path.exists(abs_path):
        logger.debug(f"[StateManager] State file not found: {abs_path}")
        return None

    try:
        with open(abs_path, "r", encoding="utf-8") as f:
            content = f.read()

        if not content.strip():
            logger.warning(f"[StateManager] State file is empty: {abs_path}")
            return None

        raw = json.loads(content)

        if not isinstance(raw, dict):
            logger.warning(f"[StateManager] State file is not a JSON object: {abs_path}")
            return None

        # Merge with defaults so every key is guaranteed to exist
        merged = {**STATE_DEFAULTS, **raw}
        return merged

    except json.JSONDecodeError as e:
        logger.warning(f"[StateManager] Corrupt JSON in {abs_path}: {e}")
        return None
    except Exception as e:
        logger.error(f"[StateManager] Failed to read state from {abs_path}: {e}")
        return None


def is_state_fresh(path: str, max_age_seconds: int = 120) -> bool:
    """Check if the state file exists and was written within max_age_seconds."""
    state = load_bot_state(path)
    if state is None:
        return False

    ts_str = state.get("timestamp")
    if not ts_str:
        return False

    try:
        last_dt = datetime.fromisoformat(str(ts_str))
        age = (datetime.now() - last_dt).total_seconds()
        return age < max_age_seconds
    except Exception:
        return False
