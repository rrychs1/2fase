---
description: Guía paso a paso para desplegar el bot en la nube (AWS/DigitalOcean)
---

# Despliegue del Bot en la Nube

Para que el bot funcione 24/7 de forma profesional, sigue estos pasos:

## 1. Preparación del Servidor (VPS)
Recomiendo una instancia **Ubuntu 22.04 LTS** con al menos 1GB de RAM.

### Instalar Docker (Ejecutar en la terminal del servidor):
```bash
sudo apt update && sudo apt install -y docker.io docker-compose
sudo systemctl start docker
sudo systemctl enable docker
```

## 2. Configuración del Bot
1. Sube tu código al servidor (usando Git o SCP).
2. Crea el archivo `.env` en la raíz del proyecto usando `nano .env`:
   - Copia el contenido de `.env.production`.
   - **IMPORTANTE**: Pon tus Claves Reales y asegúrate de que `USE_TESTNET=False`.

## 3. Ejecución Continua
Para que el bot no se detenga si cierras la sesión:

### Opción A: Usando Docker (Recomendado)
```bash
# Construir la imagen
docker build -t trading-bot .

# Ejecutar en segundo plano con autoreinicio
docker run -d --name binance-bot --restart always --env-file .env trading-bot
```

### Opción B: Ver Logs
```bash
docker logs -f binance-bot
```

## 4. Seguridad en Binance
1. En la configuración de tu API en Binance:
   - Activa "Restrict access to trusted IPs only".
   - Pega la **IP Pública** de tu servidor Cloud.
   - Activa "Enable Futures".
   
¡Tu bot ya está listo para operar en el mercado real!
