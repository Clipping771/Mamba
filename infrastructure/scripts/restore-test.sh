#!/usr/bin/env bash
# Monthly restore test (NFR-4). Restores the latest offsite backup into a THROWAWAY stack
# (separate compose project "bm-restore-test"; it binds the dev ports on 127.0.0.1, so do not
# run it next to a local dev stack) and proves it is intact:
#   - every organisation's audit hash chain verifies
#   - every evidence object re-hashes to its capture SHA-256
#
# Run on a spare machine or the server itself:
#   AGE_IDENTITY=~/blackmamba-backup.key BACKUP_REMOTE=b2:blackmamba-backups ./restore-test.sh [STAMP]
# AGE_IDENTITY is the offline private key. Delete the decrypted data afterwards (the script does).
set -Eeuo pipefail

: "${AGE_IDENTITY:?path to the age private key}"
: "${BACKUP_REMOTE:?rclone remote}"
BM_DIR="${BM_DIR:-$(cd "$(dirname "$0")/../.." && pwd)}"
STAMP="${1:-$(rclone lsf --dirs-only "$BACKUP_REMOTE" | sort | tail -1 | tr -d /)}"
WORK="$(mktemp -d /var/tmp/bm-restore.XXXXXX)"
PROJECT="bm-restore-test"
ENV_FILE="$WORK/restore.env"
COMPOSE=(docker compose -p "$PROJECT" -f "$BM_DIR/docker-compose.yml" --env-file "$ENV_FILE")

cleanup() {
  "${COMPOSE[@]}" down -v --remove-orphans >/dev/null 2>&1 || true
  rm -rf "$WORK"
}
trap cleanup EXIT
umask 077

echo "restoring backup $STAMP"
rclone copy "$BACKUP_REMOTE/$STAMP" "$WORK/backup"
(cd "$WORK/backup" && sha256sum -c "SHA256SUMS-$STAMP")

# Throwaway credentials; FIELD_ENCRYPTION_KEY/SECRET_KEY are not needed to verify integrity.
pw="$(openssl rand -hex 16)"
cat > "$ENV_FILE" <<EOF
POSTGRES_USER=blackmamba
POSTGRES_PASSWORD=$pw
POSTGRES_DB=blackmamba
MINIO_ROOT_USER=blackmamba
MINIO_ROOT_PASSWORD=$pw
S3_ACCESS_KEY=blackmamba
S3_SECRET_KEY=$pw
MINIO_KMS_SECRET_KEY=restore-key:$(openssl rand -base64 32)
SECRET_KEY=$(openssl rand -hex 32)
LLM_PROVIDER=fake
EOF

"${COMPOSE[@]}" up -d --wait postgres redis minio
"${COMPOSE[@]}" run --rm minio-init

echo "restoring PostgreSQL"
age -d -i "$AGE_IDENTITY" "$WORK/backup/postgres-$STAMP.dump.age" \
  | "${COMPOSE[@]}" exec -T postgres pg_restore -U blackmamba -d blackmamba --no-owner --exit-on-error

echo "restoring evidence objects"
age -d -i "$AGE_IDENTITY" "$WORK/backup/evidence-$STAMP.tar.age" \
  | "${COMPOSE[@]}" run --rm -T --entrypoint /bin/sh minio-init -c "
    mc alias set local http://minio:9000 blackmamba '$pw' >/dev/null &&
    tar -C /tmp -xf - && mc mirror --quiet /tmp/evidence local/evidence"

echo "verifying audit chains and evidence hashes"
"${COMPOSE[@]}" run --rm --no-deps api blackmamba verify-all

echo "RESTORE TEST PASSED for backup $STAMP"
