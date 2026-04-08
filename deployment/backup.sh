#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════
#  backup.sh — Timestamped backup of bot data
# ═══════════════════════════════════════════════════════════════
#
#  Usage:
#    bash deployment/backup.sh              # full backup
#    bash deployment/backup.sh --dry-run    # show what would happen
#
#  Crontab (daily at 03:00):
#    0 3 * * * cd /opt/pruebas && bash deployment/backup.sh >> logs/backup.log 2>&1
#
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
BACKUP_ROOT="${REPO_DIR}/backups"
TIMESTAMP=$(date '+%Y-%m-%d_%H%M%S')
BACKUP_DIR="${BACKUP_ROOT}/${TIMESTAMP}"
RETENTION_DAYS=7
DRY_RUN=false

for arg in "$@"; do
    case "$arg" in
        --dry-run) DRY_RUN=true ;;
        --help)
            echo "Usage: bash deployment/backup.sh [--dry-run]"
            echo "  Backs up DB, state files, .env, and papers to backups/<timestamp>/"
            echo "  Deletes backups older than ${RETENTION_DAYS} days."
            exit 0 ;;
    esac
done

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] BACKUP: $*"; }

log "Starting backup → ${BACKUP_DIR}"

# ── Files to back up ────────────────────────────────────────
FILES=(
    "data/trading_v3.db"
    "data/dashboard_state.json"
    "data/papers.jsonl"
    "data/alerts.jsonl"
    ".env"
    "status.json"
)

if [ "$DRY_RUN" = true ]; then
    log "[DRY-RUN] Would create: ${BACKUP_DIR}"
    for f in "${FILES[@]}"; do
        src="${REPO_DIR}/${f}"
        [ -f "$src" ] && log "[DRY-RUN] Would copy: ${f}" || log "[DRY-RUN] Skip (missing): ${f}"
    done
    log "[DRY-RUN] Would delete backups older than ${RETENTION_DAYS} days"
    exit 0
fi

mkdir -p "$BACKUP_DIR"

COPIED=0
for f in "${FILES[@]}"; do
    src="${REPO_DIR}/${f}"
    if [ -f "$src" ]; then
        # Preserve directory structure for data/ files
        dest_dir="${BACKUP_DIR}/$(dirname "$f")"
        mkdir -p "$dest_dir"
        cp "$src" "${dest_dir}/$(basename "$f")"
        COPIED=$((COPIED + 1))
    else
        log "  Skip (missing): ${f}"
    fi
done

# ── Compress ─────────────────────────────────────────────────
ARCHIVE="${BACKUP_ROOT}/${TIMESTAMP}.tar.gz"
tar -czf "$ARCHIVE" -C "$BACKUP_ROOT" "$TIMESTAMP" 2>/dev/null
rm -rf "$BACKUP_DIR"
SIZE=$(du -sh "$ARCHIVE" | cut -f1)
log "Created ${ARCHIVE} (${SIZE}, ${COPIED} files)"

# ── Retention — delete old backups ───────────────────────────
DELETED=$(find "$BACKUP_ROOT" -name "*.tar.gz" -mtime +"$RETENTION_DAYS" -print -delete 2>/dev/null | wc -l)
if [ "$DELETED" -gt 0 ]; then
    log "Pruned ${DELETED} backup(s) older than ${RETENTION_DAYS} days"
fi

TOTAL=$(find "$BACKUP_ROOT" -name "*.tar.gz" 2>/dev/null | wc -l)
log "Done. ${TOTAL} backup(s) retained."
