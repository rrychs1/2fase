# ⚡ QUICKSTART - 10 minutos para arrancar

## Requisitos
- Python 3.10+
- Claves API de Binance Futures Testnet

## Pasos

### 1️⃣ Entorno virtual (1 min)
```bash
cd binance_futures_bot
python -m venv venv
# Windows:
venv\Scripts\activate
# Linux/Mac:
source venv/bin/activate
```

### 2️⃣ Dependencias (2 min)
```bash
pip install --upgrade pip
pip install -r deployment/requirements.txt
```

### 3️⃣ Configurar claves (2 min)
```bash
# Copiar plantilla
cp .env.example .env

# Editar .env y poner tus claves de Testnet:
# BINANCE_API_KEY=tu_clave_testnet
# BINANCE_SECRET_KEY=tu_secreto_testnet
```

### 4️⃣ Obtener claves Testnet (3 min)
1. Ir a: https://testnet.binancefuture.com
2. Registrarse con email o GitHub
3. API Management → Create API Key
4. Copiar API Key y Secret → pegar en `.env`

### 5️⃣ Verificar claves (1 min)
```bash
python verify_keys.py
# Deberías ver: "✅ ¡ÉXITO! Conexión verificada correctamente en Testnet."
```

### 6️⃣ Arrancar el bot (1 min)
```bash
python main.py
```

Deberías ver:
```
ANALYSIS_ONLY activo: se omiten operaciones privadas
Starting Bot Runner...
Symbol: BTC/USDT | Regime: range | Price: 97000.00
[ITER-PAPER] BTC/USDT tf=4h price=97000.00 ...
```

### 7️⃣ Verificar estado
```bash
# En otra terminal:
python ping_bot.py
```

## ¿Problemas?
- Ver `logs/bot.log` para detalles
- Verificar que el `.env` está correcto
- Asegurar que el virtualenv está activado
