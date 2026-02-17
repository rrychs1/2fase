import hmac
import hashlib
import time
import requests

def test_manual_auth():
    api_key = 'QjXWYvcjCMGKfgrgEicpBEsL1TQpIznGFqWhbgav5PbcNSQMjhzbC6LEnMWg1EU4'
    secret = 'aZXDZ0COMbjG0gRjwZuaBSNXmeBNWw7URFDnNuUtug48yvXXFu3ezwK0tJNRgDwl'
    base_url = "https://testnet.binancefuture.com"
    endpoint = "/fapi/v2/balance"
    
    timestamp = int(time.time() * 1000)
    query_string = f"timestamp={timestamp}"
    signature = hmac.new(secret.encode('utf-8'), query_string.encode('utf-8'), hashlib.sha256).hexdigest()
    
    url = f"{base_url}{endpoint}?{query_string}&signature={signature}"
    headers = {
        'X-MBX-APIKEY': api_key
    }
    
    print(f"Testing direct auth to {url}...")
    try:
        r = requests.get(url, headers=headers, timeout=10)
        print(f"  Status: {r.status_code}")
        print(f"  Response: {r.text}")
    except Exception as e:
        print(f"  Failed: {e}")

if __name__ == "__main__":
    test_manual_auth()
