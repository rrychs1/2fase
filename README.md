# Binance Futures Trading Bot

## 🤖 Bot de Trading Híbrido para Binance Futures

Sistema de trading automatizado que combina **Grid Trading** en mercados laterales con **Trend DCA** en mercados tendenciales, con gestión de riesgo institucional y detección automática de régimen de mercado.

## ✨ Características

- **Dual Estrategia Adaptativa**: Grid + Trend DCA seleccionadas automáticamente
- **Detección de Régimen**: Clasificación trend/range con histéresis usando EMA y BB
- **Volume Profile**: Cálculo de POC/VAH/VAL para niveles de grid óptimos
- **Gestión de Riesgo**: Position sizing centralizado, kill switch diario
- **Modo Análisis**: Ejecuta sin colocar órdenes para validar lógica
- **Testnet First**: Configurado por defecto para Binance Futures Testnet
- **Logging Robusto**: Archivos rotativos + consola + registros JSONL

## 📊 Arquitectura

```
main.py → BotRunner (60s loop)
    ├── ExchangeClient (CCXT - Binance Futures)
    ├── DataEngine (OHLCV + caching)
    ├── TechnicalIndicators (EMA, MACD, RSI, ATR, BB)
    ├── VolumeProfile (POC, VAH, VAL)
    ├── RegimeDetector (trend/range classification)
    ├── StrategyRouter
    │   ├── NeutralGridStrategy (range markets)
    │   └── TrendDcaStrategy (trending markets)
    ├── RiskManager (position sizing, kill switch)
    └── ExecutionEngine (order placement)
```

## 🚀 Despliegue con Docker (DigitalOcean)

### 1. Preparar el Entorno
- **Requisitos del Droplet**: 
  - Recomendado: 1 vCPU, 1 GB RAM (mínimo).
  - Ubuntu 22.04 LTS con Docker.
- Configurar el **Firewall** del Droplet para permitir:
  - `22 (SSH)`: Acceso remoto.
  - `8000 (TCP)`: Dashboard.

### 2. Desplegar
```bash
# Sube el código y configura .env
cp .env.example .env 
# Editar .env con tus credenciales

# Iniciar servicios
docker-compose up -d --build
```

### 3. Comandos Útiles & Troubleshooting
- **Ver logs unificados**: `docker-compose logs -f`
- **Reiniciar solo el dashboard**: `docker-compose restart dashboard`
- **Verificar salud**: `curl http://localhost:8000/dashboard/health`
- **Métricas de operación**: `curl http://localhost:8000/api/metrics`

## 🛡️ Resiliencia y Aislamiento de Procesos

El sistema está diseñado siguiendo principios de **Ingeniería de Fiabilidad**:

1.  **Aislamiento Total**: El bot de trading (`main.py`) y el dashboard (`run_dashboard.py`) corren como procesos independientes.
    *   Si el dashboard falla o se reinicia, el bot mantiene sus órdenes y lógica sin interrupciones.
    *   Si el bot se detiene por un error crítico, el dashboard seguirá mostrando el último estado conocido y el historial de alertas.
2.  **Manejo de Datos Offline**: El dashboard lee estados de archivos `.json` y `.jsonl`. Si un archivo está corrupto o no existe, el dashboard muestra un estado vacío pero no se cae.
3.  **Healthcheck**: El endpoint `/dashboard/health` permite que orquestadores (Docker, PM2) monitoreen la salud interna del servidor web.
4.  **Historial Persistente**: Las alertas se guardan en `data/alerts.jsonl`, permitiendo auditoría retroactiva incluso tras reinicios.

## ⚙️ Diferencias Local vs Cloud (.env)
| Variable | Local (Desarrollo) | Cloud (Producción) |
|----------|-------------------|-------------------|
| `LOG_LEVEL` | `DEBUG` | `INFO` |
| `LOG_TO_FILE` | `true` | `false` (usa `docker logs`) |
| `DASHBOARD_HOST` | `127.0.0.1` | `0.0.0.0` |
| `TRADING_ENV` | `TESTNET` | `LIVE` (cuando estés listo) |

## 📁 Estructura del Proyecto

```
binance_futures_bot/
├── main.py                          # Entry point
├── .env.example                     # Plantilla de configuración
├── .gitignore                       # Protege archivos sensibles
├── ping_bot.py                      # Utilidad de estado
├── verify_keys.py                   # Verificador de claves API
├── config/
│   └── config_loader.py             # Gestión de configuración
├── common/
│   └── types.py                     # 20+ dataclasses tipados
├── exchange/
│   └── exchange_client.py           # Wrapper CCXT (dual client)
├── data/
│   └── data_engine.py               # Motor de datos OHLCV
├── indicators/
│   ├── technical_indicators.py      # EMA, MACD, RSI, ATR, BB
│   └── volume_profile.py            # POC, VAH, VAL
├── regime/
│   └── regime_detector.py           # Detección de régimen
├── strategy/
│   ├── neutral_grid_strategy.py     # Grid para mercados laterales
│   ├── trend_dca_strategy.py        # Trend DCA para tendencias
│   └── strategy_router.py           # Router basado en régimen
├── risk/
│   └── risk_manager.py              # Gestión centralizada de riesgo
├── execution/
│   └── execution_engine.py          # Motor de ejecución de órdenes
├── analytics/
│   └── gemini_analyst.py            # Análisis AI-ready
├── orchestration/
│   └── bot_runner.py                # Orquestador principal
├── logging_monitoring/
│   └── logger.py                    # Logger con rotación
├── deployment/
│   ├── requirements.txt             # Dependencias Python
│   ├── binance_bot.service          # Servicio systemd
│   └── RUNBOOK.md                   # Guía de despliegue VPS
├── docs/
│   ├── ARCHITECTURE.md              # Documentación técnica
│   └── DESIGN_DECISIONS.md          # Decisiones de diseño
└── logs/                            # Directorio de logs (auto-creado)
```

## ⚙️ Configuración

| Variable | Default | Descripción |
|----------|---------|-------------|
| `BINANCE_API_KEY` | - | Clave API de Binance |
| `BINANCE_SECRET_KEY` | - | Secreto API de Binance |
| `USE_TESTNET` | `True` | Usar Testnet |
| `ANALYSIS_ONLY` | `True` | No colocar órdenes reales |
| `SYMBOLS` | `BTC/USDT,ETH/USDT` | Pares a monitorear |
| `LEVERAGE` | `3` | Apalancamiento |
| `MAX_RISK_PER_TRADE` | `0.01` | Riesgo máximo por trade (1%) |
| `DAILY_LOSS_LIMIT` | `0.02` | Límite de pérdida diaria (2%) |
| `POLLING_INTERVAL` | `60` | Intervalo del loop en segundos |

## ⚠️ Advertencias

- **SIEMPRE probar en Testnet primero**
- **NUNCA** subir `.env` a repositorios públicos
- Código en esqueletos necesita completarse
- Empezar conservador: 1% riesgo, 3x apalancamiento
- Monitorear diariamente las primeras semanas

## 📝 Próximos Pasos

1. Completar lógica de estrategias (~30-45 hrs)
2. Probar en testnet 1-2 semanas
3. Ajustar parámetros según resultados
4. Solo entonces considerar modo LIVE (capital pequeño)

## 📄 Licencia

Uso privado. No distribuir sin autorización.
