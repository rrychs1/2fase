# Usar una imagen ligera de Python
FROM python:3.11-slim

WORKDIR /app

# Instalar dependencias del sistema
RUN apt-get update && apt-get install -y \
    build-essential \
    supervisor \
    && rm -rf /var/lib/apt/lists/*

# Copiar requerimientos e instalar
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar el resto del codigo
COPY . .

# Crear directorio de logs
RUN mkdir -p logs

# Exponer puerto del dashboard
EXPOSE 5050

# Usar supervisord para correr bot + dashboard
COPY supervisord.conf /etc/supervisor/conf.d/supervisord.conf
CMD ["supervisord", "-c", "/etc/supervisor/conf.d/supervisord.conf"]
