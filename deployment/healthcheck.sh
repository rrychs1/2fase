#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════
#  healthcheck.sh — External monitoring for bot + dashboard
# ═══════════════════════════════════════════════════════════════
#
#  Usage:
#    bash deployment/healthcheck.sh              # single check
#    bash deployment/healthcheck.sh --auto-fix   # restart on failure
#
#  Crontab (every 5 min):
#    */5 * * * * cd /opt/pruebas && bash deployment/healthcheck.sh --auto-fix >> logs/healthcheck.log 2>&1
#
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
HEALTH_URL="http://localhost:${DASHBOARD_PORT:-8000}/dashboard/health"
FAIL_FILE="/tmp/healthcheck_failures"
MAX_FAILURES=3      # consecutive failures before action
AUTO_FIX=false
LOG_FILE="${REPO_DIR}/logs/healthcheck.log"

# Telegram alert (optional — uses .env variables)
source "${REPO_DIR}/.env" 2>/dev/null || true
TELEGRAM_TOKEN="${TELEGRAM_TOKEN:-}"
TELEGRAM_CHAT_ID="${TELEGRAM_CHAT_ID:-}"

for arg in "$@"; do
    case "$arg" in
        --auto-fix) AUTO_FIX=true ;;
        --help)
            echo "Usage: bash deployment/healthcheck.sh [--auto-fix]"
            echo "  Checks /dashboard/health and optionally restarts on failure."
            exit 0 ;;
    esac
done

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] HEALTH: $*"; }

mkdir -p "$(dirname "$LOG_FILE")"

# ── Perform the check ────────────────────────────────────────
HTTP_CODE=$(curl -s -o /tmp/health_response.json -w '%{http_code}' "$HEALTH_URL" --connect-timeout 5 --max-time 10 2>/dev/null || echo "000")

if [ "$HTTP_CODE" = "200" ]; then
    # Parse JSON response
    STATUS=$(python3 -c "import json; d=json.load(open('/tmp/health_response.json')); print(d.get('status','unknown'))" 2>/dev/null || echo "unknown")
    BOT_STATE=$(python3 -c "import json; d=json.load(open('/tmp/health_response.json')); print(d.get('can_read_bot_state', False))" 2>/dev/null || echo "False")
    DB_OK=$(python3 -c "import json; d=json.load(open('/tmp/health_response.json')); print(d.get('database_ok', False))" 2>/dev/null || echo "False")

    if [ "$STATUS" = "healthy" ] && [ "$DB_OK" = "True" ]; then
        # All good — reset failure counter
        echo "0" > "$FAIL_FILE"
        log "OK (HTTP ${HTTP_CODE}, bot_state=${BOT_STATE}, db=${DB_OK})"
        rm -f /tmp/health_response.json
        exit 0
    else
        log "DEGRADED (HTTP ${HTTP_CODE}, status=${STATUS}, bot_state=${BOT_STATE}, db=${DB_OK})"
    fi
else
    log "FAILED (HTTP ${HTTP_CODE} from ${HEALTH_URL})"
fi

# ── Track consecutive failures ───────────────────────────────
FAILURES=$(cat "$FAIL_FILE" 2>/dev/null || echo "0")
FAILURES=$((FAILURES + 1))
echo "$FAILURES" > "$FAIL_FILE"

log "Consecutive failures: ${FAILURES}/${MAX_FAILURES}"

# ── Take action if threshold reached ────────────────────────
if [ "$FAILURES" -ge "$MAX_FAILURES" ]; then
    log "ALERT: ${FAILURES} consecutive failures!"

    # Send Telegram notification
    if [ -n "$TELEGRAM_TOKEN" ] && [ -n "$TELEGRAM_CHAT_ID" ]; then
        MSG="🚨 *Bot Healthcheck FAILED*%0A${FAILURES} consecutive failures on $(hostname)%0AHTTP: ${HTTP_CODE}%0ATime: $(date '+%H:%M:%S')"
        curl -s "https://api.telegram.org/bot${TELEGRAM_TOKEN}/sendMessage?chat_id=${TELEGRAM_CHAT_ID}&text=${MSG}&parse_mode=Markdown" > /dev/null 2>&1 || true
        log "Telegram alert sent"
    fi

    # Auto-restart containers
    if [ "$AUTO_FIX" = true ]; then
        log "Auto-fix: restarting containers..."
        cd "$REPO_DIR"
        docker compose restart 2>&1 | tee -a "$LOG_FILE"
        echo "0" > "$FAIL_FILE"
        log "Containers restarted. Will re-check on next cron run."

        # Notify recovery attempt
        if [ -n "$TELEGRAM_TOKEN" ] && [ -n "$TELEGRAM_CHAT_ID" ]; then
            MSG="🔄 Bot containers restarted automatically on $(hostname)"
            curl -s "https://api.telegram.org/bot${TELEGRAM_TOKEN}/sendMessage?chat_id=${TELEGRAM_CHAT_ID}&text=${MSG}" > /dev/null 2>&1 || true
        fi
    else
        log "Auto-fix disabled. Run with --auto-fix to enable automatic restart."
    fi
fi

rm -f /tmp/health_response.json
exit 1
