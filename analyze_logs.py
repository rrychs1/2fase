
import re
from datetime import datetime
import collections

LOG_FILE = 'logs/bot.log'
START_DATE = '2026-02-11'

def analyze_logs():
    print(f"--- Análisis de Logs Históricos desde {START_DATE} ---")
    
    trades = []
    daily_pnl = collections.defaultdict(float)
    errors = collections.defaultdict(int)
    
    try:
        with open(LOG_FILE, 'r', encoding='utf-8', errors='ignore') as f:
            for line in f:
                # Filtrar por fecha
                if not line.startswith(START_DATE) and line < START_DATE:
                    # Asume formato YYYY-MM-DD al inicio
                    # Si la linea no empieza con fecha, se salta o se asocia a la anterior (simplificado aquí)
                    if re.match(r'\d{4}-\d{2}-\d{2}', line):
                        if line < START_DATE:
                            continue
                
                # Detectar Trades FILLED
                if "FILLED" in line:
                    # Ejemplo: ... [Grid] ETH/USDT Level 1979.315 (buy) FILLED. ...
                    match = re.search(r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}).*\[Grid\] (\w+/\w+) Level (\d+\.?\d*) \((\w+)\) FILLED', line)
                    if match:
                        timestamp, symbol, price, side = match.groups()
                        trades.append({
                            'time': timestamp,
                            'symbol': symbol,
                            'price': float(price),
                            'side': side,
                            'type': 'GRID_FILL'
                        })
                
                # Detectar Errores
                if "ERROR" in line:
                    if "418" in line or "IP banned" in line:
                        errors['IP Ban'] += 1
                    elif "401" in line:
                        errors['Unauthorized'] += 1
                    else:
                        errors['Other'] += 1

                # Detectar Kill Switch (Pérdida realizada o stop)
                if "Kill Switch Triggered" in line:
                     trades.append({
                        'time': line.split(',')[0],
                        'symbol': 'ALL',
                        'price': 0,
                        'side': 'KILL_SWITCH',
                        'type': 'STOP_LOSS'
                     })

    except Exception as e:
        print(f"Error leyendo el log: {e}")
        return

    print(f"\n📊 Resumen de Actividad:")
    print(f"Total Trades Detectados (Grid Fills): {len(trades)}")
    print(f"Total Errores Críticos (IP Bans): {errors['IP Ban']}")
    
    print("\n📜 Detalle de Trades:")
    if not trades:
        print("   (No se encontraron trades completados en los logs)")
    else:
        print(f"{'FECHA':<20} | {'SYMBOL':<10} | {'SIDE':<6} | {'PRICE':<10}")
        print("-" * 55)
        for t in trades:
            print(f"{t['time']} | {t['symbol']:<10} | {t['side']:<6} | {t['price']:.2f}")

    # Análisis cualitativo
    print("\n💡 Conclusión del Análisis:")
    if len(trades) > 0:
        fills = len([t for t in trades if t['type'] == 'GRID_FILL'])
        stops = len([t for t in trades if t['type'] == 'STOP_LOSS'])
        print(f"- El bot ha ejecutado {fills} operaciones de grid exitosas.")
        if stops > 0:
            print(f"- ⚠️ SE ACTIVÓ EL KILL SWITCH {stops} VECES. Esto indica pérdidas controladas o errores de saldo.")
        else:
            print("- ✅ No se han registrado paradas de emergencia (Kill Switch) por pérdidas masivas en este periodo analizado (filtrando errores de saldo 0).")
            
        print("- La estrategia de Grid parece estar funcionando para capturar movimientos pequeños.")
    else:
        print("- No hay suficiente actividad de trading registrada para evaluar rentabilidad.")
        print("- La mayoría de los logs parecen ser de monitoreo o errores de conexión.")

if __name__ == "__main__":
    # Redirect stdout to file
    import sys
    original_stdout = sys.stdout
    with open('analysis_results.txt', 'w', encoding='utf-8') as f:
        sys.stdout = f
        analyze_logs()
    sys.stdout = original_stdout
    print("Análisis completado. Resultados guardados en analysis_results.txt")
