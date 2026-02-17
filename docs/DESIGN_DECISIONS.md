# Decisiones de Diseño

## 1. ¿Por qué CCXT en vez de python-binance?
- CCXT soporta 100+ exchanges con API unificada
- Posibilidad de migrar a otros brokers futuros
- Comunidad activa y documentación extensa
- python-binance incluido como dependencia por compatibilidad

## 2. ¿Por qué dual client (público + autenticado)?
- Las peticiones de datos de mercado (OHLCV) no requieren autenticación
- Usar claves API en peticiones públicas puede causar errores -2008
- El cliente público evita estos problemas completamente

## 3. ¿Por qué EMA(50/200) para tendencia?
- Golden Cross / Death Cross son ampliamente reconocidos
- Suficiente suavizado para evitar whipsaws en cripto
- Complementados con MACD para confirmación

## 4. ¿Por qué Bollinger Bands Width para régimen?
- Mide directamente la compresión de volatilidad
- BB_width bajo = mercado lateral → Grid
- BB_width alto = mercado en movimiento → Trend DCA
- Simple y efectivo para el caso de uso

## 5. ¿Por qué Volume Profile para Grid?
- POC indica el precio "justo" del mercado
- VAH/VAL definen los extremos de la distribución
- Grid dentro de Value Area tiene mayor probabilidad de fill
- Más sofisticado que grid de porcentaje fijo

## 6. ¿Por qué ANALYSIS_ONLY como default?
- Seguridad ante todo
- Permite validar la lógica completa sin riesgo
- Fácil de desactivar cuando estés listo
- Evita pérdidas accidentales por configuración incorrecta

## 7. ¿Por qué 60 segundos de polling?
- Timeframe más bajo usado es 1h
- No necesitamos actualizar más frecuentemente
- Reduce consumo de API rate limits
- Suficiente para estrategias de medio plazo

## 8. ¿Por qué modular en vez de monolítico?
- Cada módulo testeable independientemente
- Fácil de reemplazar componentes (ej: otro exchange)
- Separación de concerns clara
- Más fácil de debuggear

## 9. ¿Por qué JSONL para paper records?
- Formato append-only (no corruption)
- Fácil de cargar con `pd.read_json(lines=True)`
- Formato humano-legible
- No requiere base de datos

## 10. ¿Por qué testnet por default?
- Principio de menor privilegio
- Protege contra errores de configuración
- Flujo: testnet → paper → live con capital mínimo → escalar
