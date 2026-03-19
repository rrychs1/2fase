# Base image
FROM python:3.11-slim

# Prevent write bytecode and force unbuffered logging natively
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1
ENV DASHBOARD_HOST "0.0.0.0"

# Install system dependencies (build-essential for TA Libs, sqlite3 for DB, supervisor for process management)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    libffi-dev \
    sqlite3 \
    supervisor \
    && rm -rf /var/lib/apt/lists/*

# Create application directory
WORKDIR /app

# Upgrade pip securely
RUN pip install --upgrade pip setuptools wheel

# Install Python requirements
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

# Create necessary local directories for SQLite and standard Logs binding
RUN mkdir -p /app/data /app/logs /tmp

# Copy all source code maps natively
COPY . /app/

# Expose Dashboard and Prometheus Metrics Native Ports
EXPOSE 8050 8000

# Run native supervisor mapping dynamically loading the application logic loops
CMD ["supervisord", "-n", "-c", "/app/deployment/supervisord.conf"]
