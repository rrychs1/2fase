import os
import time
import hmac
import hashlib
import requests
import ccxt
from dotenv import load_dotenv
from urllib.parse import urlencode

load_dotenv()

def verify_keys():
    print("--- Verificador de Claves Binance (Mejorado) ---")
    
    api_key = os.getenv('BINANCE_API_KEY')
    secret_key = os.getenv('BINANCE_API_SECRET') or os.getenv('BINANCE_SECRET_KEY')
    trading_env = os.getenv('TRADING_ENV', 'TESTNET').upper()
    use_testnet = trading_env in ['TESTNET', 'DEMO'] or os.getenv('USE_TESTNET', 'True').lower() == 'true'
    
    if not api_key or not secret_key:
        print("❌ ERROR: No se encontraron claves API en .env")
        return

    print(f"Configuración: {'TESTNET' if use_testnet else 'MAINNET'}")
    print(f"API Key: {api_key[:5]}...{api_key[-5:]}")

    if use_testnet:
        # Método 1: Verificación Directa (Más robusta para Testnet)
        print("\n[1] Verificando con Petición Directa (Recomendado para Testnet)...")
        base_url = "https://demo-fapi.binance.com"
        endpoint = "/fapi/v2/balance"
        
        try:
            timestamp = int(time.time() * 1000)
            params = {'timestamp': timestamp, 'recvWindow': 5000}
            query_string = urlencode(params)
            signature = hmac.new(
                secret_key.encode('utf-8'),
                query_string.encode('utf-8'),
                hashlib.sha256
            ).hexdigest()
            
            url = f"{base_url}{endpoint}?{query_string}&signature={signature}"
            headers = {'X-MBX-APIKEY': api_key}
            
            r = requests.get(url, headers=headers, timeout=10)
            
            if r.status_code == 200:
                print("✅ ¡ÉXITO! Conexión verificada correctamente en Testnet.")
                data = r.json()
                # Buscar saldo USDT
                usdt_balance = next((item for item in data if item["asset"] == "USDT"), None)
                if usdt_balance:
                    print(f"   Saldo Wallet: {usdt_balance['balance']}")
                    print(f"   Saldo Cross Wallet: {usdt_balance.get('crossWalletBalance', 'N/A')}")
                    print(f"   PnL No Realizado: {usdt_balance.get('crossUnPnl', 'N/A')}")
                else:
                    print("   Saldo: No se encontraron fondos en USDT.")
                
                # Chequear Posiciones Abiertas
                print("\n   --- Posiciones Abiertas ---")
                try:
                    pos_url = f"{base_url}/fapi/v2/positionRisk"
                    timestamp = int(time.time() * 1000)
                    params = {'timestamp': timestamp, 'recvWindow': 5000}
                    query_string = urlencode(params)
                    signature = hmac.new(
                        secret_key.encode('utf-8'),
                        query_string.encode('utf-8'),
                        hashlib.sha256
                    ).hexdigest()
                    
                    r_pos = requests.get(f"{pos_url}?{query_string}&signature={signature}", headers=headers, timeout=10)
                    if r_pos.status_code == 200:
                        positions = r_pos.json()
                        active_positions = [p for p in positions if float(p['positionAmt']) != 0]
                        if active_positions:
                            for p in active_positions:
                                print(f"   🔴 {p['symbol']} | Cantidad: {p['positionAmt']} | Entry: {p['entryPrice']} | PnL: {p['unRealizedProfit']}")
                        else:
                            print("   ✅ No hay posiciones abiertas.")
                    else:
                        print(f"   ❌ Error al obtener posiciones: {r_pos.status_code}")
                except Exception as ex:
                    print(f"   ❌ Excepción al buscar posiciones: {ex}")

                return
            else:
                print(f"❌ Fallo en petición directa: {r.status_code}")
                print(f"   Respuesta: {r.text}")
        except Exception as e:
            print(f"❌ Excepción en petición directa: {e}")

    # Método 2: CCXT (Fallback o Mainnet)
    print(f"\n[2] Verificando con CCXT standard ({'Testnet' if use_testnet else 'Mainnet'})...")
    try:
        exchange = ccxt.binance({
            'apiKey': api_key,
            'secret': secret_key,
            'options': {'defaultType': 'future'}
        })
        
        if use_testnet:
            # Manually override URLs for Demo Trading (sandbox deprecated)
            demo_fapi = 'https://demo-fapi.binance.com/fapi/v1'
            exchange.urls['api']['public'] = demo_fapi
            exchange.urls['api']['private'] = demo_fapi
            exchange.urls['api']['fapiPublic'] = demo_fapi
            exchange.urls['api']['fapiPrivate'] = demo_fapi
        
        balance = exchange.fetch_balance()
        print("✅ ¡ÉXITO! Conexión verificada con CCXT.")
        print(f"   Saldo Total USDT: {balance['total'].get('USDT', 0)}")
        
    except Exception as e:
        print(f"⚠️ CCXT Error (común en Testnet): {str(e)}")
        if use_testnet:
            print("   Nota: Si la verificación [1] funcionó, ignora este error de CCXT.")

if __name__ == "__main__":
    verify_keys()
