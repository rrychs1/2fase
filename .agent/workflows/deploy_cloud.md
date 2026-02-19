---
description: Guia paso a paso para desplegar el bot + dashboard en DigitalOcean
---

# Despliegue del Bot + Dashboard en DigitalOcean

## Prerequisitos
- Cuenta de DigitalOcean (usa tu GitHub Student Pack para $200 de credito)
- Repositorio del bot subido a GitHub

## 1. Crear Droplet

1. Ve a [cloud.digitalocean.com](https://cloud.digitalocean.com)
2. Crea un **Droplet**:
   - **OS**: Ubuntu 22.04 LTS
   - **Plan**: Basic $6/mes (1 vCPU, 1GB RAM) — suficiente para el bot
   - **Region**: New York o la mas cercana
   - **Autenticacion**: SSH Key (recomendado) o Password

## 2. Conectarse al Servidor

```bash
ssh root@<TU_DROPLET_IP>
```

## 3. Instalar Docker

// turbo
```bash
sudo apt update && sudo apt install -y docker.io
sudo systemctl start docker && sudo systemctl enable docker
```

## 4. Clonar Repositorio

```bash
cd /opt
git clone https://github.com/<TU_USUARIO>/<TU_REPO>.git trading-bot
cd trading-bot
```

## 5. Crear Archivo .env

```bash
nano .env
```

Pegar el contenido (usa tus credenciales reales):
```env
BINANCE_API_KEY=tu_api_key
BINANCE_SECRET_KEY=tu_secret_key
USE_TESTNET=True
ANALYSIS_ONLY=False
SYMBOLS=BTC/USDT,ETH/USDT
LEVERAGE=3
POLLING_INTERVAL=60
TELEGRAM_BOT_TOKEN=tu_token
TELEGRAM_CHAT_ID=tu_chat_id
```

## 6. Construir y Ejecutar

// turbo
```bash
docker build -t trading-bot .
```

```bash
docker run -d \
  --name binance-bot \
  --restart always \
  --env-file .env \
  -p 5050:5050 \
  -v /opt/trading-bot/logs:/app/logs \
  -v /opt/trading-bot/data:/app/data \
  trading-bot
```

## 7. Verificar

// turbo
```bash
# Ver logs del bot
docker logs -f binance-bot

# Ver estado
docker ps

# Acceder al dashboard
# Abre en tu navegador: http://<TU_DROPLET_IP>:5050
```

## 8. Configurar Firewall

```bash
ufw allow 22     # SSH
ufw allow 5050   # Dashboard
ufw enable
```

## 9. Seguridad en Binance

1. En la configuracion de tu API en Binance:
   - Activa "Restrict access to trusted IPs only"
   - Pega la **IP Publica** de tu Droplet
   - Activa "Enable Futures"

## Comandos Utiles

```bash
# Reiniciar bot
docker restart binance-bot

# Detener bot
docker stop binance-bot

# Ver logs en tiempo real
docker logs -f --tail 100 binance-bot

# Actualizar codigo
cd /opt/trading-bot
git pull
docker build -t trading-bot .
docker stop binance-bot && docker rm binance-bot
# Volver a ejecutar el comando del paso 6
```
