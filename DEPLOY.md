# Despliegue en DigitalOcean con Docker

> Guía completa para desplegar el bot de trading en un Droplet nuevo.
> Tiempo estimado: 15–20 minutos.

---

## 1. Prerrequisitos

### 1.1. Crear Droplet

| Parámetro | Valor recomendado |
|-----------|-------------------|
| **OS** | Ubuntu 22.04 LTS |
| **Plan** | Basic, 2 GB RAM / 1 vCPU ($12/mes) |
| **Región** | **Frankfurt (FRA1)** o **Amsterdam (AMS3)** — baja latencia a Binance EU. Evitar regiones en países donde Binance está restringido (EE.UU., UK). |
| **Auth** | SSH Key (no password) |
| **Hostname** | `trading-bot` |

> **⚠️ Importante sobre la región**: Si eliges una región donde Binance está bloqueado (ej. ciertas IPs de EE.UU.), recibirás **Error 451** al conectar. Frankfurt y Ámsterdam funcionan bien con Binance Futures Testnet y Live.

### 1.2. Instalar Docker y Docker Compose

```bash
ssh root@YOUR_DROPLET_IP

# Actualizar sistema
apt update && apt upgrade -y

# Instalar Docker (incluye Docker Compose v2)
curl -fsSL https://get.docker.com | sh
systemctl enable --now docker

# Verificar instalación
docker --version          # esperar 24+
docker compose version    # esperar v2.x

# Instalar extras
apt install -y git ufw

# Firewall: abrir solo SSH y dashboard
ufw allow OpenSSH
ufw allow 8000/tcp
ufw --force enable
```

### 1.3. Clonar el repositorio

```bash
cd /opt
git clone https://github.com/rrychs1/Anti-bot-bi.git pruebas
cd pruebas
```

---

## 2. Paso a paso

### 2.1. Configurar `.env`

```bash
cp .env.example .env
nano .env
```

**Cambios mínimos requeridos:**
```env
# Reemplazar con tus claves reales
BINANCE_API_KEY=tu_clave_api
BINANCE_API_SECRET=tu_secreto_api
```

**Opciones comunes:**
```env
# Modo seguro (papel) — recomendado para primera vez
TRADING_ENV=TESTNET
ANALYSIS_ONLY=True
TELEGRAM_ENABLED=false

# Dashboard accesible desde fuera
DASHBOARD_HOST=0.0.0.0
DASHBOARD_PORT=8000
```

Guardar y cerrar (`Ctrl+X`, `Y`, `Enter` en nano).

### 2.2. Crear directorios de persistencia

```bash
mkdir -p data logs backups
```

### 2.3. Construir la imagen

```bash
docker compose build --no-cache
```

Esperar a ver al final:
```
[BUILD] All critical imports verified.
```

Si ves este mensaje, la imagen está correcta.

### 2.4. Levantar los servicios

```bash
docker compose up -d
```

### 2.5. Verificar que todo está arriba

```bash
# Estado de los containers
docker compose ps

# Esperar ~45s y verificar salud
docker compose ps
```

Salida esperada:
```
NAME                STATUS                    PORTS
trading-bot         Up (healthy)
trading-dashboard   Up (healthy)              0.0.0.0:8000->8000/tcp
```

### 2.6. Abrir el dashboard

En tu navegador:
```
http://YOUR_DROPLET_IP:8000
```

Verificar con curl desde el servidor:
```bash
curl -s http://localhost:8000/dashboard/health | python3 -m json.tool
```

Respuesta esperada:
```json
{
    "status": "healthy",
    "database_ok": true,
    "can_read_bot_state": true,
    "database_has_data": true
}
```

### 2.7. Revisar logs

```bash
# Bot (en tiempo real)
docker compose logs -f trading-bot

# Dashboard
docker compose logs -f trading-dashboard

# Últimas 50 líneas del bot
docker compose logs --tail=50 trading-bot

# Ambos servicios a la vez
docker compose logs -f
```

---

## 3. Operaciones del día a día

### Actualizar el código (deploy)

```bash
cd /opt/pruebas
bash deployment/deploy.sh
```

El script hace: `git pull` → backup → build → restart → healthcheck → rollback si falla.

### Backups

```bash
# Manual
bash deployment/backup.sh

# Automático (agregar a crontab)
crontab -e
0 3 * * * cd /opt/pruebas && bash deployment/backup.sh >> logs/backup.log 2>&1
```

### Monitoreo

```bash
# Healthcheck manual
bash deployment/healthcheck.sh

# Automático con auto-restart (cada 5 min)
crontab -e
*/5 * * * * cd /opt/pruebas && bash deployment/healthcheck.sh --auto-fix >> logs/healthcheck.log 2>&1
```

### Comandos útiles

```bash
# Reiniciar solo el bot
docker compose restart trading-bot

# Parar todo
docker compose down

# Ver uso de recursos
docker stats --no-stream

# Reset del Kill Switch
docker compose exec trading-bot python -c "
import json
with open('data/risk_state.json', 'r') as f: s=json.load(f)
s['is_kill_switch_active'] = False
with open('data/risk_state.json', 'w') as f: json.dump(s, f, indent=2)
print('Kill Switch reset')
"
```

---

## 4. Solución de problemas típicos

### Error: `COPY failed: file not found in build context: requirements.txt`

**Causa**: El archivo `.dockerignore` contiene una regla `*.txt` que bloquea `requirements.txt`.

**Solución**: Verificar que `.dockerignore` **NO** tiene `*.txt`:
```bash
grep '*.txt' .dockerignore
```
Si aparece, eliminar esa línea. El `.dockerignore` actual del repo ya está corregido.

---

### Error: `ModuleNotFoundError: No module named 'ccxt'` (o `flask`, `pandas`, etc.)

**Causa**: La imagen se construyó sin instalar dependencias, o `requirements.txt` no se copió al build context (ver error anterior).

**Solución**:
```bash
# 1. Verificar que requirements.txt tiene las dependencias
cat requirements.txt

# 2. Reconstruir desde cero
docker compose build --no-cache

# 3. Verificar que la línea de verificación aparece:
#    "[BUILD] All critical imports verified."
```

Si el error persiste, verificar que la librería está listada en `requirements.txt` y volver a construir.

---

### Error 451: `HTTP 451 Unavailable For Legal Reasons` de Binance

**Causa**: La IP del Droplet está en un país donde Binance está restringido (EE.UU., UK, Ontario/Canadá, etc.).

**Solución**:
1. Verificar la IP del Droplet:
   ```bash
   curl -s ifconfig.me
   # Buscar la geolocalización en https://ipinfo.io/YOUR_IP
   ```

2. Crear un nuevo Droplet en una región permitida:
   | Región | Código | Estado |
   |--------|--------|--------|
   | Frankfurt | FRA1 | ✅ Funciona |
   | Amsterdam | AMS3 | ✅ Funciona |
   | Singapore | SGP1 | ✅ Funciona |
   | New York | NYC1 | ❌ Puede fallar |
   | San Francisco | SFO3 | ❌ Puede fallar |
   | London | LON1 | ❌ Restringido |

3. Migrar:
   ```bash
   # En el nuevo Droplet:
   cd /opt
   git clone https://github.com/rrychs1/Anti-bot-bi.git pruebas
   cd pruebas
   # Copiar .env del viejo servidor:
   scp root@OLD_IP:/opt/pruebas/.env .
   # Copiar data (opcional, para mantener historial):
   scp -r root@OLD_IP:/opt/pruebas/data/ ./data/
   docker compose up -d --build
   ```

---

### Error: `Exchange connection failed` o `Invalid API-key`

**Causa**: Claves incorrectas o tipo de clave incorrecto.

**Solución**:
- Para **Testnet**: usar claves de https://testnet.binancefuture.com
- Para **Live**: usar claves de https://www.binance.com con permisos de Futures
- Verificar que no hay espacios extra en `.env`:
  ```bash
  grep -n 'BINANCE' .env
  ```

---

### Error: `can_read_bot_state: false` en el healthcheck

**Causa**: El bot no está escribiendo el state file, o lo escribió hace más de 2 minutos.

**Solución**:
```bash
# 1. Verificar que el bot está corriendo
docker compose ps trading-bot

# 2. Revisar logs del bot
docker compose logs --tail=30 trading-bot

# 3. Verificar que el state file existe y es reciente
ls -la data/dashboard_state.json
cat data/dashboard_state.json | python3 -m json.tool | head -5
```

---

### Dashboard no carga o muestra "--" en todos los paneles

**Causa**: El dashboard no puede leer datos del bot.

**Solución**:
```bash
# 1. Verificar conectividad interna
docker compose exec trading-dashboard curl -s http://localhost:8000/dashboard/health

# 2. Verificar que los volúmenes están montados
docker compose exec trading-dashboard ls -la data/

# 3. Verificar que el firewall permite el puerto
ufw status | grep 8000
```

---

### El bot se reinicia constantemente

**Solución**:
```bash
# Ver la razón del crash
docker compose logs --tail=100 trading-bot

# Causas comunes:
# - Kill Switch activo → resetear (ver arriba)
# - API keys inválidas → verificar .env
# - OOM (sin memoria) → verificar: docker stats --no-stream
```

---

## 5. Seguridad

- [ ] `.env` está en `.gitignore` — **nunca** commitear
- [ ] SSH usa autenticación por clave, no contraseña
- [ ] `ufw` activo con solo puertos necesarios (22, 8000)
- [ ] Claves API rotadas cada 90 días
- [ ] Updates automáticos habilitados:
  ```bash
  apt install -y unattended-upgrades
  dpkg-reconfigure -plow unattended-upgrades
  ```
