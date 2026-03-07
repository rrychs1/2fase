# Usar una imagen ligera de Python
FROM python:3.11-slim

WORKDIR /app

# Instalar dependencias del sistema
RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copiar requerimientos e instalar
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar el resto del codigo
COPY . .

# Crear directorios de persistencia
RUN mkdir -p logs data

# Exponer el puerto del dashboard (debe coincidir con .env DASHBOARD_PORT)
EXPOSE 8000

# Por defecto corre el bot (puede sobreescribirse en docker-compose)
CMD ["python", "main.py"]
