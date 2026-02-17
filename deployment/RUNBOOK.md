# Deployment Runbook - Binance Futures Trading Bot

## Pre-requisitos

- **VPS**: Ubuntu 22.04+ con al menos 1GB RAM
- **Python**: 3.10+
- **Claves API**: Binance Futures Testnet

## Paso 1: Preparar el Servidor

```bash
# Actualizar sistema
sudo apt update && sudo apt upgrade -y

# Instalar Python y dependencias del sistema
sudo apt install -y python3.10 python3.10-venv python3-pip git

# Crear usuario para el bot (opcional pero recomendado)
sudo useradd -m -s /bin/bash tradingbot
sudo su - tradingbot
```

## Paso 2: Clonar/Copiar el Proyecto

```bash
mkdir -p ~/binance_futures_bot
cd ~/binance_futures_bot
# Copiar todos los archivos del proyecto aquí
```

## Paso 3: Configurar Entorno Virtual

```bash
python3.10 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r deployment/requirements.txt
```

## Paso 4: Configurar Variables de Entorno

```bash
cp .env.example .env
nano .env
# Configurar:
# BINANCE_API_KEY=tu_clave_testnet
# BINANCE_SECRET_KEY=tu_secreto_testnet
# USE_TESTNET=True
# ANALYSIS_ONLY=True
```

## Paso 5: Probar Manualmente

```bash
python main.py
# Verificar que inicia correctamente
# Ctrl+C para detener
```

## Paso 6: Instalar como Servicio

```bash
# Copiar servicio
sudo cp deployment/binance_bot.service /etc/systemd/system/

# Editar si es necesario (cambiar User, paths)
sudo nano /etc/systemd/system/binance_bot.service

# Habilitar e iniciar
sudo systemctl daemon-reload
sudo systemctl enable binance_bot.service
sudo systemctl start binance_bot.service
```

## Paso 7: Monitorear

```bash
# Ver logs en tiempo real
sudo journalctl -u binance_bot.service -f

# Ver estado
sudo systemctl status binance_bot.service

# Ver logs del bot
tail -f ~/binance_futures_bot/logs/bot.log

# Ping rápido
cd ~/binance_futures_bot && source venv/bin/activate && python ping_bot.py
```

## Comandos de Mantenimiento

```bash
# Reiniciar
sudo systemctl restart binance_bot.service

# Detener
sudo systemctl stop binance_bot.service

# Ver logs de los últimos 30 minutos
sudo journalctl -u binance_bot.service --since "30 min ago"

# Actualizar código
cd ~/binance_futures_bot
sudo systemctl stop binance_bot.service
# ... copiar archivos actualizados ...
source venv/bin/activate
pip install -r deployment/requirements.txt
sudo systemctl start binance_bot.service
```

## Troubleshooting

| Error | Solución |
|-------|----------|
| `Failed to initialize exchange` | Verificar claves API en `.env` |
| `Invalid API-key` | Sin espacios extra en `.env`, claves de FUTURES Testnet |
| `Module not found` | Verificar virtualenv: `source venv/bin/activate` |
| Bot se detiene | Revisar `logs/bot.log` |
| Servicio no arranca | `sudo journalctl -u binance_bot.service -n 50` |

## Seguridad

⚠️ **IMPORTANTE:**
- NUNCA subir `.env` a git
- Usar firewall (`ufw`)
- Certificados SSL si hay interfaz web
- Monitorear accesos SSH
- Rotar claves API periódicamente
