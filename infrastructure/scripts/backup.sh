#!/usr/bin/env bash
# Daily encrypted offsite backup of PostgreSQL + evidence objects (NFR-4).
#
# Requires on the host: docker, age (https://age-encryption.org), rclone (configured remote).
# Config (environment or /etc/black-mamba/backup.env):
#   BM_DIR             path of the checkout            (default /opt/black-mamba)
#   BACKUP_AGE_RECIPIENT  age public key (age1...). The PRIVATE key lives offline, never on the server.
#   BACKUP_REMOTE      rclone destination, e.g. b2:blackmamba-backups
#   BACKUP_KEEP_DAYS   remote retention                 (default 30)
#   HEALTHCHECK_URL    optional ping URL (e.g. healthchecks.io) for success/failure alerts
#
# Cron (03:15 UTC daily):  15 3 * * * root /opt/black-mamba/infrastructure/scripts/backup.sh
set -Eeuo pipefail

[[ -f /etc/black-mamba/backup.env ]] && source /etc/black-mamba/backup.env
BM_DIR="${BM_DIR:-/opt/black-mamba}"
: "${BACKUP_AGE_RECIPIENT:?set BACKUP_AGE_RECIPIENT}"
: "${BACKUP_REMOTE:?set BACKUP_REMOTE}"
KEEP_DAYS="${BACKUP_KEEP_DAYS:-30}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
WORK="$(mktemp -d /var/tmp/bm-backup.XXXXXX)"
COMPOSE=(docker compose -f "$BM_DIR/docker-compose.prod.yml" --env-file "$BM_DIR/.env.production")

ping() { [[ -n "${HEALTHCHECK_URL:-}" ]] && curl -fsS -m 10 --retry 3 "$HEALTHCHECK_URL$1" >/dev/null || true; }
cleanup() { rm -rf "$WORK"; }
fail() { echo "backup FAILED at line $1" >&2; ping /fail; cleanup; exit 1; }
trap 'fail $LINENO' ERR
trap cleanup EXIT
umask 077
ping /start

cd "$BM_DIR"
set -a; source .env.production; set +a

echo "[$STAMP] verifying integrity before backup"
"${COMPOSE[@]}" exec -T api blackmamba verify-all

echo "dumping PostgreSQL"
"${COMPOSE[@]}" exec -T postgres pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --format=custom --no-owner \
  | age -r "$BACKUP_AGE_RECIPIENT" > "$WORK/postgres-$STAMP.dump.age"

echo "exporting evidence objects"
"${COMPOSE[@]}" run --rm --no-deps -T --entrypoint /bin/sh minio-init -c "
  mc alias set local http://minio:9000 \"\$MINIO_ROOT_USER\" \"\$MINIO_ROOT_PASSWORD\" >/dev/null &&
  mkdir -p /tmp/evidence && mc mirror --quiet local/\${S3_BUCKET:-evidence} /tmp/evidence >/dev/null &&
  tar -C /tmp -cf - evidence" \
  | age -r "$BACKUP_AGE_RECIPIENT" > "$WORK/evidence-$STAMP.tar.age"

sha256sum "$WORK"/*.age > "$WORK/SHA256SUMS-$STAMP"

echo "uploading to $BACKUP_REMOTE/$STAMP"
rclone copy "$WORK" "$BACKUP_REMOTE/$STAMP" --transfers 2
rclone delete "$BACKUP_REMOTE" --min-age "${KEEP_DAYS}d" || true
rclone rmdirs "$BACKUP_REMOTE" --leave-root || true

echo "backup $STAMP complete"
ping ""
