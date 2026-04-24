#!/usr/bin/env bash
set -euo pipefail

# Same-box backup script (Docker Compose, single Postgres service):
# - Dumps both databases (psc_main + psc_coupon) using pg_dump custom format.
# - Archives uploads folders (PSC + coupon engine uploads).
# - Keeps last N days of backups (default 14).
#
# Usage (run from repo root on server):
#   ./deploy/backup_same_box.sh
#
# Optional env vars:
#   BACKUP_DIR=/var/backups/psc
#   RETAIN_DAYS=14

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

BACKUP_DIR="${BACKUP_DIR:-/var/backups/psc}"
RETAIN_DAYS="${RETAIN_DAYS:-14}"

ENV_FILE="${ROOT_DIR}/.env"
if [[ -f "$ENV_FILE" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
fi

DATE_UTC="$(date -u +%Y%m%d_%H%M%S)"
TARGET_DIR="${BACKUP_DIR}/${DATE_UTC}"

mkdir -p "$TARGET_DIR"

echo "Backup target: $TARGET_DIR"

if ! command -v docker >/dev/null 2>&1; then
  echo "ERROR: docker not found."
  exit 1
fi

if [[ -z "${PSC_DB_PASSWORD:-}" || -z "${COUPON_DB_PASSWORD:-}" ]]; then
  echo "ERROR: PSC_DB_PASSWORD / COUPON_DB_PASSWORD not set."
  echo "Create /opt/psc/.env with these values (see CLOUD_MIGRATION.md)."
  exit 1
fi

if ! docker compose ps >/dev/null 2>&1; then
  echo "ERROR: docker compose is not available or the project is not running in: $ROOT_DIR"
  exit 1
fi

echo "Dumping DB: psc_main"
docker compose exec -T psc_db bash -lc \
  "PGPASSWORD=\"${PSC_DB_PASSWORD:-}\" pg_dump -Fc -U psc_admin -d psc_main" \
  > "${TARGET_DIR}/psc_main.dump"

echo "Dumping DB: psc_coupon"
docker compose exec -T psc_db bash -lc \
  "PGPASSWORD=\"${PSC_DB_PASSWORD:-}\" pg_dump -Fc -U psc_admin -d psc_coupon" \
  > "${TARGET_DIR}/psc_coupon.dump"

echo "Archiving uploads"
tar -czf "${TARGET_DIR}/uploads_psc.tar.gz" -C "${ROOT_DIR}" "Psparshcare/static/uploads" 2>/dev/null || true
tar -czf "${TARGET_DIR}/uploads_coupon.tar.gz" -C "${ROOT_DIR}" "psc_coupens/psc_coupens_app/static/uploads" 2>/dev/null || true

cat > "${TARGET_DIR}/README.txt" <<EOF
Backup created (UTC): ${DATE_UTC}

Files:
- psc_main.dump         : pg_dump custom format (restore with pg_restore)
- psc_coupon.dump       : pg_dump custom format (restore with pg_restore)
- uploads_psc.tar.gz    : PSC uploads folder archive
- uploads_coupon.tar.gz : Coupon engine uploads folder archive
EOF

echo "Rotating backups older than ${RETAIN_DAYS} days in: ${BACKUP_DIR}"
find "${BACKUP_DIR}" -mindepth 1 -maxdepth 1 -type d -mtime +"${RETAIN_DAYS}" -print0 2>/dev/null | xargs -0r rm -rf

echo "Backup complete."
