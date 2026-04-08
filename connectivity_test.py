import requests


def test_exchange_info():
    url = "https://demo-fapi.binance.com/fapi/v1/exchangeInfo"
    print(f"Testing {url}...")
    try:
        r = requests.get(url, timeout=10)
        print(f"  Status: {r.status_code}")
        if r.status_code == 200:
            data = r.json()
            print(f"  Success! Symbols count: {len(data['symbols'])}")
            # Find BTCUSDT
            btc = next((s for s in data["symbols"] if s["symbol"] == "BTCUSDT"), None)
            print(f"  BTCUSDT: {btc['status'] if btc else 'Not found'}")
        else:
            print(f"  Response: {r.text[:500]}")
    except Exception as e:
        print(f"  Failed: {e}")


if __name__ == "__main__":
    test_exchange_info()
