"""
Start the Trading Bot Dashboard.
Usage: python run_dashboard.py [--port 5050] [--no-browser]
"""
import argparse
import os
import sys
import webbrowser
import threading
from dotenv import load_dotenv

# Load env variables early
load_dotenv()

# Add project root to path so Flask can find modules
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def main():
    # Priority: Env Var > CLI Arg > Default
    env_port = os.getenv("DASHBOARD_PORT")
    default_port = int(env_port) if env_port else 5050
    
    parser = argparse.ArgumentParser(description="Trading Bot Dashboard")
    parser.add_argument("--port", type=int, default=default_port, help=f"Port (default: {default_port})")
    parser.add_argument("--no-browser", action="store_true", help="Don't auto-open browser")
    args = parser.parse_args()

    from dashboard.app import app

    # In Docker/Droplet we usually want no-browser and host 0.0.0.0
    is_docker = os.path.exists('/.dockerenv')
    host = os.getenv("DASHBOARD_HOST", "0.0.0.0" if is_docker else "127.0.0.1")
    
    if not args.no_browser and not is_docker:
        # Open browser after a short delay to let Flask start
        def open_browser():
            import time
            time.sleep(1.2)
            webbrowser.open(f"http://{host}:{args.port}")
        threading.Thread(target=open_browser, daemon=True).start()

    print(f"\n  Dashboard -> http://{host}:{args.port}")
    print(f"  Press Ctrl+C to stop\n")
    app.run(host=host, port=args.port, debug=False)


if __name__ == "__main__":
    main()
