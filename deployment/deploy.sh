#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════
#  deploy.sh — Zero-downtime deploy for the trading bot
# ═══════════════════════════════════════════════════════════════
#
#  Usage:
#    cd /opt/pruebas
#    bash deployment/deploy.sh              # normal deploy
#    bash deployment/deploy.sh --no-backup  # skip pre-deploy backup
#    bash deployment/deploy.sh --dry-run    # show what would happen
#
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
DEPLOY_LOG="${REPO_DIR}/logs/deploy.log"
HEALTH_URL="http://localhost:${DASHBOARD_PORT:-8000}/dashboard/health"
BACKUP_SCRIPT="${REPO_DIR}/deployment/backup.sh"
TIMEOUT=90          # seconds to wait for healthy status after restart
NO_BACKUP=false
DRY_RUN=false

# ── Parse flags ──────────────────────────────────────────────
for arg in "$@"; do
    case "$arg" in
        --no-backup) NO_BACKUP=true ;;
        --dry-run)   DRY_RUN=true ;;
        --help)
            echo "Usage: bash deployment/deploy.sh [--no-backup] [--dry-run]"
            exit 0 ;;
    esac
done

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$DEPLOY_LOG"; }
die() { log "FATAL: $*"; exit 1; }

mkdir -p "$(dirname "$DEPLOY_LOG")"

log "═══ Deploy started ═══"
log "Repo: ${REPO_DIR}"
cd "$REPO_DIR" || die "Cannot cd to ${REPO_DIR}"

# ── 1. Pre-flight checks ────────────────────────────────────
command -v docker >/dev/null   || die "docker not found"
command -v git >/dev/null      || die "git not found"
[ -f ".env" ]                  || die ".env file missing"
[ -f "docker-compose.yml" ]    || die "docker-compose.yml missing"
[ -f "Dockerfile" ]            || die "Dockerfile missing"

CURRENT_COMMIT=$(git rev-parse --short HEAD 2>/dev/null || echo "unknown")
log "Current commit: ${CURRENT_COMMIT}"

# ── 2. Pre-deploy backup ────────────────────────────────────
if [ "$NO_BACKUP" = false ] && [ -f "$BACKUP_SCRIPT" ]; then
    log "Running pre-deploy backup..."
    if [ "$DRY_RUN" = true ]; then
        log "[DRY-RUN] Would run: bash ${BACKUP_SCRIPT}"
    else
        bash "$BACKUP_SCRIPT" || log "WARNING: Backup failed, continuing anyway"
    fi
else
    log "Skipping backup (--no-backup or script not found)"
fi

# ── 3. Pull latest code ─────────────────────────────────────
log "Pulling latest code..."
if [ "$DRY_RUN" = true ]; then
    log "[DRY-RUN] Would run: git pull --ff-only"
else
    git pull --ff-only || die "git pull failed (merge conflict?). Fix manually."
fi

NEW_COMMIT=$(git rev-parse --short HEAD 2>/dev/null || echo "unknown")
log "New commit: ${NEW_COMMIT}"

if [ "$CURRENT_COMMIT" = "$NEW_COMMIT" ]; then
    log "No changes detected. Rebuilding anyway to catch Dockerfile changes."
fi

# ── 4. Build & restart ──────────────────────────────────────
log "Building images..."
if [ "$DRY_RUN" = true ]; then
    log "[DRY-RUN] Would run: docker compose build"
    log "[DRY-RUN] Would run: docker compose up -d"
    log "═══ Deploy dry-run complete ═══"
    exit 0
fi

docker compose build --no-cache 2>&1 | tail -5 | tee -a "$DEPLOY_LOG"
docker compose up -d 2>&1 | tee -a "$DEPLOY_LOG"

# ── 5. Post-deploy healthcheck ──────────────────────────────
log "Waiting for healthy status (max ${TIMEOUT}s)..."
ELAPSED=0
while [ $ELAPSED -lt $TIMEOUT ]; do
    sleep 5
    ELAPSED=$((ELAPSED + 5))

    HTTP_CODE=$(curl -s -o /dev/null -w '%{http_code}' "$HEALTH_URL" 2>/dev/null || echo "000")
    if [ "$HTTP_CODE" = "200" ]; then
        # Parse the JSON to check can_read_bot_state
        HEALTH=$(curl -s "$HEALTH_URL" 2>/dev/null || echo "{}")
        DB_OK=$(echo "$HEALTH" | python3 -c "import sys,json; print(json.load(sys.stdin).get('database_ok', False))" 2>/dev/null || echo "False")

        if [ "$DB_OK" = "True" ]; then
            log "Healthcheck PASSED after ${ELAPSED}s (HTTP ${HTTP_CODE}, DB OK)"
            log "═══ Deploy successful ═══"
            exit 0
        fi
        log "  [${ELAPSED}s] HTTP ${HTTP_CODE} but DB not ready yet..."
    else
        log "  [${ELAPSED}s] HTTP ${HTTP_CODE} — waiting..."
    fi
done

# ── 6. Rollback on failure ──────────────────────────────────
log "ALERT: Healthcheck failed after ${TIMEOUT}s!"
log "Rolling back to commit ${CURRENT_COMMIT}..."
git checkout "$CURRENT_COMMIT" 2>/dev/null || log "WARNING: git checkout failed"
docker compose build --no-cache 2>&1 | tail -3 | tee -a "$DEPLOY_LOG"
docker compose up -d 2>&1 | tee -a "$DEPLOY_LOG"
log "═══ Deploy FAILED — rolled back to ${CURRENT_COMMIT} ═══"
exit 1
