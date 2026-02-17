# Arquitectura del Sistema - Binance Futures Trading Bot

## Visión General

El bot está diseñado como un sistema modular de trading para Binance Futures que opera en un loop de 60 segundos. Cada iteración sigue un pipeline secuencial de: obtención de datos → cálculo de indicadores → detección de régimen → generación de señales → validación de riesgo → ejecución.

## Flujo de Datos

```
Exchange (Binance API)
    ↓ OHLCV (4h, 1h)
DataEngine
    ↓ DataFrames (pandas)
TechnicalIndicators + VolumeProfile
    ↓ DataFrames enriquecidos + VP dict
RegimeDetector
    ↓ "trend" | "range"
StrategyRouter
    ├─ range → NeutralGridStrategy → grid signals
    └─ trend → TrendDcaStrategy → trend signals
        ↓ Signal list
RiskManager (validación)
    ↓ Approved signals
ExecutionEngine
    ↓ Orders → Exchange
```

## Módulos Principales

### 1. `config/config_loader.py`
Gestiona toda la configuración via `.env`:
- Claves API (separación demo/live)
- Parámetros de estrategia
- Límites de riesgo
- Timeframes

### 2. `exchange/exchange_client.py`
Wrapper sobre CCXT con:
- **Dual client**: público (datos) + autenticado (órdenes)
- Configuración automática de URLs testnet
- Fallback multi-nivel para `fetch_balance`
- Desactivación de `fetchCurrencies` (evita errores SAPI)

### 3. `data/data_engine.py`
Motor de datos simplificado:
- Obtención de OHLCV via `fetch_ohlcv`
- Caché en memoria por (symbol, timeframe)
- Método `update_ohlcv` para actualizaciones incrementales

### 4. `indicators/`
#### `technical_indicators.py`
Indicadores técnicos via pandas_ta:
- EMA(50), EMA(200) - detección de tendencia
- MACD(12,26,9) - confirmación de tendencia
- RSI(14) - overbought/oversold
- ATR(14) - volatilidad / stop loss
- Bollinger Bands(20,2) - ancho de banda

#### `volume_profile.py`
Perfil de volumen:
- POC (Point of Control) - precio con mayor volumen
- VAH/VAL (Value Area High/Low) - 70% del volumen
- Usado por NeutralGridStrategy para niveles de grid

### 5. `regime/regime_detector.py`
Clasificador de régimen con histéresis:
- **Trend**: EMA distance > 2% AND BB_width above average
- **Range**: todo lo demás
- Tolerante a NaN y columnas faltantes

### 6. `strategy/`
#### `neutral_grid_strategy.py`
Grid trading para mercados laterales:
- Niveles de compra entre VAL y POC
- Niveles de venta entre POC y VAH
- Distribución uniforme de capital
- Rebuild cuando precio rompe VAH o VAL

#### `trend_dca_strategy.py`
Trend following con DCA:
- Señal alcista: EMA_fast > EMA_slow AND MACD > 0
- Señal bajista: EMA_fast < EMA_slow AND MACD < 0
- Entrada en pullback al EMA_fast
- Niveles DCA a 1% de distancia

#### `strategy_router.py`
Router basado en régimen:
- Range → NeutralGridStrategy
- Trend → TrendDcaStrategy

### 7. `risk/risk_manager.py`
Gestión de riesgo centralizada:
- Position sizing por % de equity
- Kill switch diario por drawdown
- Enforcement de apalancamiento

### 8. `execution/execution_engine.py`
Motor de ejecución:
- Órdenes limit y market
- Modo ANALYSIS_ONLY para paper trading
- Precisión de amounts y prices via exchange

### 9. `orchestration/bot_runner.py`
Orquestador principal:
- Loop principal con polling configurable
- Logging detallado por iteración
- Registros JSONL para análisis posterior
- Status file para monitoreo externo
- Manejo robusto de errores

## Decisiones de Diseño Clave

1. **Dual Exchange Client**: Evita errores de autenticación en datos públicos
2. **ANALYSIS_ONLY mode**: Permite validar toda la lógica sin riesgo
3. **Tolerancia a NaN**: Todos los módulos manejan datos faltantes
4. **JSONL logging**: Formato simple para análisis con pandas
5. **Módulos independientes**: Cada componente puede testearse aislado

## Seguridad

- Claves API nunca en código fuente
- Separación de entornos (testnet/live)
- Kill switch por drawdown diario
- Limits de exposición por trade
- Logging de todas las decisiones
