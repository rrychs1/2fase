# ═══════════════════════════════════════════════════════════════
#  Dockerfile — Multi-stage build for the trading bot
# ═══════════════════════════════════════════════════════════════
#
#  Stage 1 (builder): compile C extensions (numpy, scipy, etc.)
#  Stage 2 (runner):  lean production image (~200 MB vs ~800 MB)
#

# ── Stage 1: Builder ─────────────────────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /build

# Install build tools needed to compile wheels (numpy, scipy, ta, etc.)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies into a separate prefix
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt


# ── Stage 2: Runner (production) ─────────────────────────────
FROM python:3.11-slim AS runner

# Prevent .pyc files & enable real-time log output
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Copy compiled Python packages from builder
COPY --from=builder /install /usr/local

# Minimal runtime dependency (curl for healthchecks)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create a non-root user for security
RUN groupadd --gid 1000 botuser \
    && useradd --uid 1000 --gid botuser --create-home botuser

# Copy application source
COPY --chown=botuser:botuser . .

# Ensure persistence directories exist and are writable
RUN mkdir -p logs data && chown -R botuser:botuser logs data

# ── Build-time verification ──────────────────────────────────
# Compile all .py files to catch syntax errors early.
# Then verify critical imports are available.
RUN python -m compileall -q /app \
    && python -c "\
import flask, ccxt, pandas, numpy, ta, scipy, sklearn; \
from state.state_manager import write_bot_state, load_bot_state; \
from data.db_manager import DbManager; \
from config.config_loader import Config; \
print('[BUILD] All critical imports verified.')"

# Dashboard port (must match .env DASHBOARD_PORT)
EXPOSE 8000

# Switch to non-root user
USER botuser

# Default: run the bot (overridden in docker-compose for dashboard)
CMD ["python", "main.py"]
