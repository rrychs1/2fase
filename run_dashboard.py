"""
Start the Trading Bot Dashboard.
Usage: python run_dashboard.py [--port 5050] [--no-browser]
"""
import argparse
import os
import sys
import webbrowser
import threading

# Add project root to path so Flask can find modules
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def main():
    parser = argparse.ArgumentParser(description="Trading Bot Dashboard")
    parser.add_argument("--port", type=int, default=5050, help="Port (default: 5050)")
    parser.add_argument("--no-browser", action="store_true", help="Don't auto-open browser")
    args = parser.parse_args()

    from dashboard.app import app

    if not args.no_browser:
        # Open browser after a short delay to let Flask start
        def open_browser():
            import time
            time.sleep(1.2)
            webbrowser.open(f"http://localhost:{args.port}")
        threading.Thread(target=open_browser, daemon=True).start()

    print(f"\n  Dashboard -> http://localhost:{args.port}")
    print(f"  Press Ctrl+C to stop\n")
    app.run(host="0.0.0.0", port=args.port, debug=False)


if __name__ == "__main__":
    main()
