"""
Start the Trading Bot Dashboard.
Usage: python run_dashboard.py [--port 5050] [--no-browser]

Features:
  - Detects port conflicts and auto-selects a free port
  - Prevents multiple instances via lock file
  - Logs the accessible URL with public/local IP
  - Port configurable via DASHBOARD_PORT env var
"""

import argparse
import os
import sys
import socket
import webbrowser
import threading
import atexit
from dotenv import load_dotenv

# Load env variables early
load_dotenv()

# Add project root to path so Flask can find modules
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

LOCK_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".dashboard.lock")


def _is_port_in_use(host: str, port: int) -> bool:
    """Check if a port is already bound."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1)
        try:
            s.bind((host, port))
            return False
        except OSError:
            return True


def _find_free_port(host: str, start_port: int, max_attempts: int = 20) -> int:
    """Scan upward from start_port to find a free port."""
    for offset in range(max_attempts):
        candidate = start_port + offset
        if not _is_port_in_use(host, candidate):
            return candidate
    raise RuntimeError(
        f"Could not find a free port in range {start_port}-{start_port + max_attempts - 1}"
    )


def _get_local_ip() -> str:
    """Best-effort detection of the machine's LAN IP address."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"


def _acquire_lock() -> bool:
    """Prevent multiple dashboard instances via a lock file with PID."""
    if os.path.exists(LOCK_FILE):
        try:
            with open(LOCK_FILE, "r") as f:
                old_pid = int(f.read().strip())
            # Check if the old process is still alive
            try:
                os.kill(old_pid, 0)
                # Process exists — another instance is running
                return False
            except OSError:
                # Process is dead — stale lock file, safe to override
                pass
        except (ValueError, IOError):
            # Corrupt lock file — remove and continue
            pass

    with open(LOCK_FILE, "w") as f:
        f.write(str(os.getpid()))
    return True


def _release_lock():
    """Remove the lock file on exit."""
    try:
        if os.path.exists(LOCK_FILE):
            os.remove(LOCK_FILE)
    except OSError:
        pass


def main():
    # Priority: Env Var > CLI Arg > Default
    env_port = os.getenv("DASHBOARD_PORT")
    default_port = int(env_port) if env_port else 5050

    parser = argparse.ArgumentParser(description="Trading Bot Dashboard")
    parser.add_argument(
        "--port", type=int, default=default_port, help=f"Port (default: {default_port})"
    )
    parser.add_argument(
        "--no-browser", action="store_true", help="Don't auto-open browser"
    )
    args = parser.parse_args()

    # ── Single-instance guard ────────────────────────────────
    if not _acquire_lock():
        print(
            "\n  ERROR: Another dashboard instance is already running.\n"
            f"  Lock file: {LOCK_FILE}\n"
            "  If this is incorrect, delete the lock file and retry.\n"
        )
        sys.exit(1)
    atexit.register(_release_lock)

    # ── Port conflict detection ──────────────────────────────
    is_docker = os.path.exists("/.dockerenv")
    host = os.getenv("DASHBOARD_HOST", "0.0.0.0" if is_docker else "127.0.0.1")
    port = args.port

    if _is_port_in_use(host, port):
        print(f"\n  WARNING: Port {port} is already in use.")
        try:
            port = _find_free_port(host, port + 1)
            print(f"  Auto-selected free port: {port}\n")
        except RuntimeError as e:
            print(f"  ERROR: {e}")
            sys.exit(1)

    from dashboard.app import app

    # ── Log accessible URLs ──────────────────────────────────
    local_ip = _get_local_ip()
    print("\n  ╔══════════════════════════════════════════╗")
    print("  ║       Trading Bot Dashboard              ║")
    print("  ╠══════════════════════════════════════════╣")
    if host == "0.0.0.0":
        print(f"  ║  Local:   http://127.0.0.1:{port:<14s}║")
        print(f"  ║  Network: http://{local_ip}:{port:<{20 - len(local_ip)}s}║")
    else:
        print(f"  ║  URL:     http://{host}:{port:<{20 - len(host)}s}║")
    print("  ╠══════════════════════════════════════════╣")
    print("  ║  Press Ctrl+C to stop                    ║")
    print("  ╚══════════════════════════════════════════╝\n")

    if not args.no_browser and not is_docker:
        browse_url = (
            f"http://127.0.0.1:{port}" if host == "0.0.0.0" else f"http://{host}:{port}"
        )

        def open_browser():
            import time

            time.sleep(1.2)
            webbrowser.open(browse_url)

        threading.Thread(target=open_browser, daemon=True).start()

    app.run(host=host, port=port, debug=False)


if __name__ == "__main__":
    main()
