import ccxt
import os
from dotenv import load_dotenv

load_dotenv()

def verify_keys():
    api_key = os.getenv('BINANCE_API_KEY')
    secret_key = os.getenv('BINANCE_SECRET_KEY')
    
    if not api_key or not secret_key:
        print("ERROR: No se encontraron claves API en .env")
        print("Asegúrate de tener BINANCE_API_KEY y BINANCE_SECRET_KEY en tu archivo .env")
        return
    
    print("--- Verificador de Claves Binance ---")
    print(f"API Key (primeros 5): {api_key[:5]}...")
    
    # 1. Probar con endpoints de PRODUCCIÓN (Demo Trading moderno a veces usa estos)
    print("\nProbando con endpoints de PRODUCCIÓN...")
    exchange_prod = ccxt.binance({
        'apiKey': api_key,
        'secret': secret_key,
        'options': {'defaultType': 'future'}
    })
    try:
        balance = exchange_prod.fetch_balance()
        print("¡ÉXITO en Producción! Estas llaves son para el entorno real (o Demo moderna).")
        return
    except Exception as e:
        print(f"Fallo en Producción: {e}")

    # 2. Probar con endpoints de TESTNET (Forzado Manual)
    print("\nProbando con endpoints de TESTNET (Forzado Manual)...")
    exchange_test = ccxt.binance({
        'apiKey': api_key,
        'secret': secret_key,
        'options': {'defaultType': 'future'}
    })
    # Forzar URLs de testnet ya que set_sandbox_mode falla en CCXT moderno para Binance
    exchange_test.urls['api']['fapiPublic'] = 'https://testnet.binancefuture.com/fapi/v1'
    exchange_test.urls['api']['fapiPrivate'] = 'https://testnet.binancefuture.com/fapi/v1'
    try:
        balance = exchange_test.fetch_balance()
        print("¡ÉXITO en Testnet! Estas llaves son para el entorno de pruebas tradicional.")
        return
    except Exception as e:
        print(f"Fallo en Testnet: {e}")

    # 3. Probar con endpoints de DEMO (URL alternativa reportada)
    print("\nProbando con endpoints de DEMO (fapi.binance.com con keys demo)...")
    exchange_demo = ccxt.binance({
        'apiKey': api_key,
        'secret': secret_key,
        'options': {'defaultType': 'future'}
    })
    try:
        balance = exchange_demo.fetch_balance()
        print("¡ÉXITO en fapi.binance.com! Estas llaves funcionan en el endpoint estándar de futuros.")
        return
    except Exception as e:
        print(f"Fallo en fapi.binance.com: {e}")

    print("\nLas llaves NO funcionan en ningún entorno conocido de la API.")
    print("Por favor, asegúrate de que en la configuración de la API en Binance:")
    print("1. 'Enable Futures' esté marcado.")
    print("2. Las llaves sean para la API, no solo para la web.")

if __name__ == "__main__":
    verify_keys()
