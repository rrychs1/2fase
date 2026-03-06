# Deployment Runbook — Binance Futures Bot en DigitalOcean

## Requisitos

- Ubuntu 22.04 LTS Droplet (1 vCPU, **2 GB RAM mínimo*)
- Acceso SSH al servidor
- Cuenta en Git (GitHub o GitLab) con el código del bot

---

## Paso 1: Crear el Droplet en DigitalOcean

1. Ir a [cloud.digitalocean.com](https://cloud.digitalocean.com) → **Create Droplet**
2. Imagen: **Ubuntu 22.04 LTS**
3. Plan: **Basic → Regular → $12/mo (2 vCPU, 2 GB RAM)**
4. Región: elige la más cercana (New York / Amsterdam)
5. Autenticación: **SSH Key** (recomendado)
6. Crear el Droplet y anotar la IP pública

---

## Paso 2: Preparar el Servidor

```bash
# Conectarse por SSH
ssh root@TU_IP_DROPLET

# Actualizar el sistema
apt update && apt upgrade -y

# Instalar Docker CE
curl -fsSL https://get.docker.com | sh
systemctl enable docker
systemctl start docker

# Instalar Docker Compose v2
apt install -y docker-compose-plugin

# Instalar utilidades
apt install -y git ufw curl

# Configurar firewall
ufw allow OpenSSH
ufw allow 8000/tcp    # Dashboard (opcional si no lo necesitas público)
ufw --force enable
```

---

## Paso 3: Subir el Código

### Opción A: Con Git (recomendado)

```bash
# En tu máquina local — primera vez
cd "c:\Users\rrych\Documents\Bot codigo de Claude"
git init
git remote add origin https://github.com/TU_USUARIO/TU_REPO.git
git add .
git commit -m "Initial commit"
git push -u origin main

# En el servidor DigitalOcean
git clone https://github.com/TU_USUARIO/TU_REPO.git bot
cd bot
```

### Opción B: Con rsync (sin Git)

```bash
# Desde tu máquina Windows (PowerShell)
rsync -avz --exclude='.env' --exclude='venv/' --exclude='*.db' \
  "c:/Users/rrych/Documents/Bot codigo de Claude/" \
  root@TU_IP:/root/bot/
```

---

## Paso 4: Configurar el .env en el Servidor

```bash
# En el servidor
cd /root/bot
cp .env.example .env
nano .env
```

Configurar las siguientes variables:

```env
# === CLAVES DE API ===
BINANCE_API_KEY=TU_API_KEY_REAL
BINANCE_SECRET_KEY=TU_SECRET_KEY_REAL

# === MODO (usar TESTNET primero) ===
TRADING_ENV=TESTNET
USE_TESTNET=True
ANALYSIS_ONLY=False

# === RIESGO ===
LEVERAGE=20
MAX_RISK_PER_TRADE=0.01
MAX_DAILY_LOSS=0.05
DAILY_LOSS_LIMIT=0.05
KILL_SWITCH_ENABLED=True

# === ACTIVOS ===
SYMBOLS=BTC/USDT,ETH/USDT
POLLING_INTERVAL=60

# === TELEGRAM ===
TELEGRAM_TOKEN=TU_TOKEN
TELEGRAM_CHAT_ID=TU_CHAT_ID

# === DASHBOARD ===
DASHBOARD_PORT=8000
DASHBOARD_HOST=0.0.0.0
```

---

## Paso 5: Levantar con Docker

```bash
cd /root/bot

# Construir imágenes
docker compose build

# Arrancar en segundo plano
docker compose up -d

# Verificar que están corriendo
docker compose ps

# Ver logs del bot en tiempo real
docker compose logs -f trading-bot

# Verificar healthcheck del dashboard
curl http://localhost:8000/dashboard/health
```

---

## Paso 6: Verificar que Funciona

Esperar ~60 segundos y revisar los logs. Debes ver:

```
[INFO] Exchange connection verified. Equity: XXXX USDT
[INFO] Leverage set to 20x for BTC/USDT
[INFO] Starting Async Bot Runner [Mode: Testnet]...
```

Y en Telegram llegará la notificación de inicio.

---

## Comandos de Mantenimiento

```bash
# Ver estado de los contenedores
docker compose ps

# Ver logs (últimas 100 líneas)
docker compose logs --tail=100 trading-bot

# Reiniciar el bot (después de un cambio)
docker compose restart trading-bot

# Actualizar el código y relanzar
git pull origin main
docker compose down
docker compose build
docker compose up -d

# Parar todo
docker compose down

# Ver uso de recursos
docker stats
```

---

## Monitoreo Rápido

```bash
# Estado del bot y trades del día
docker compose exec trading-bot python monitor_testnet.py

# Revisar el risk_state
docker compose exec trading-bot cat risk_state.json

# Resetear Kill Switch si es necesario
docker compose exec trading-bot python -c "
import json
with open('risk_state.json', 'r') as f: s=json.load(f)
s['is_kill_switch_active'] = False
with open('risk_state.json', 'w') as f: json.dump(s, f, indent=2)
print('Kill Switch reseteado')
"
```

---

## Troubleshooting

| Error | Solución |
|-------|----------|
| `Exchange connection failed` | Verificar `BINANCE_API_KEY` en `.env` |
| `Invalid API-key` | Las claves deben ser de **Futures Demo** (demo.binance.com) |
| `Kill Switch ACTIVE` | Ejecutar el comando de reset arriba |
| Dashboard no carga | `ufw allow 8000/tcp` y esperar 15s para healthcheck |
| Bot se detiene solo | `docker compose logs trading-bot` para ver el error |

---

## Seguridad

- **NUNCA** subir `.env` a Git (ya está en `.gitignore`)
- Rotar las claves API de Binance cada 3 meses
- SSH con clave pública, no contraseña
- `ufw` activo con solo los puertos necesarios
