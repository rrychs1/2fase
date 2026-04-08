import os
import time
import hmac
import hashlib
import requests
import ccxt
import pandas as pd
from urllib.parse import urlencode
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()


def check_trades():
    print("--- Análisis de Transacciones (Income) ---")

    api_key = os.getenv("BINANCE_API_KEY")
    secret_key = os.getenv("BINANCE_SECRET_KEY")

    if not api_key or not secret_key:
        print("Error: Claves no encontradas.")
        return

    # Fetch Income History (Source of Truth for Balance)
    print("\n--- Balance Change History (24h) ---")

    income_endpoint = "/fapi/v1/income"
    base_url = "https://testnet.binancefuture.com"

    try:
        timestamp = int(time.time() * 1000)
        # Buscar ultimas 24h
        start_time = int((datetime.now() - timedelta(days=1)).timestamp() * 1000)

        params = {
            "startTime": start_time,
            "limit": 1000,
            "timestamp": timestamp,
            "recvWindow": 5000,
        }

        query_string = urlencode(params)
        signature = hmac.new(
            secret_key.encode("utf-8"), query_string.encode("utf-8"), hashlib.sha256
        ).hexdigest()

        url = f"{base_url}{income_endpoint}?{query_string}&signature={signature}"
        headers = {"X-MBX-APIKEY": api_key}

        r = requests.get(url, headers=headers, timeout=10)

        if r.status_code == 200:
            income_data = r.json()
            if income_data:
                print(f"✅ Se encontraron {len(income_data)} registros de income.")
                df_inc = pd.DataFrame(income_data)
                df_inc["time"] = pd.to_datetime(df_inc["time"], unit="ms")

                # Filtrar hoy
                today_str = datetime.now().strftime("%Y-%m-%d")
                df_today = df_inc[df_inc["time"].dt.strftime("%Y-%m-%d") == today_str]

                total_income_pnl = 0.0

                print(
                    f"\n{'TIME':<20} | {'SYMBOL':<10} | {'TYPE':<15} | {'AMOUNT':<15}"
                )
                print("-" * 65)

                for _, row in df_today.iterrows():
                    print(
                        f"{row['time']} | {row['symbol']:<10} | {row['incomeType']:<15} | {row['income']:<15}"
                    )
                    total_income_pnl += float(row["income"])

                print(f"\n💰 Cambio de Balance HOY: {total_income_pnl:.2f} USDT")
            else:
                print("❌ No se encontraron registros de income.")
        else:
            print(f"❌ Error fetching income: {r.status_code} {r.text}")

    except Exception as e:
        print(f"Error general: {e}")


if __name__ == "__main__":
    check_trades()
