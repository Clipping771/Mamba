# Deploying BLACK MAMBA (single VPS)

This guide puts BLACK MAMBA on one Linux server with automatic HTTPS, only port 443 open,
daily encrypted offsite backups, a monthly restore test, GitHub Actions deploys and
basic monitoring. Access is invite-only.

```
Internet ──443──▶ Caddy (TLS) ──▶ web (Next.js BFF) ──▶ api (FastAPI) ──▶ postgres / redis / minio
                                                          worker (Chromium) ──▶ public web (archiving)
```

Only Caddy publishes a port. `api` is never reachable from the internet; the browser only
talks to the web app, which forwards `/api/bm/*` to the API with the session token.
`postgres`, `redis` and `minio` sit on an internal Docker network with no internet access.

## 1. Server

- Ubuntu 24.04 LTS, 2 vCPU / 4 GB RAM / 80 GB disk is a comfortable start
  (Chromium and WeasyPrint are the heaviest parts). Add disk as evidence grows.
- A DNS `A`/`AAAA` record for your domain (e.g. `app.example.org`) pointing at the server.
- A non-root sudo user with SSH key login; disable password SSH login.

```bash
sudo apt update && sudo apt -y upgrade
sudo apt -y install ca-certificates curl git ufw age rclone unattended-upgrades
sudo dpkg-reconfigure -plow unattended-upgrades
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker "$USER"   # log out and back in
```

### Firewall: 443 only (plus SSH from your IP)

```bash
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow from <YOUR.ADMIN.IP> to any port 22 proto tcp
sudo ufw allow 443/tcp
sudo ufw allow 443/udp      # HTTP/3
sudo ufw enable
```

Caddy gets certificates with the TLS-ALPN challenge on 443, so port 80 stays closed.
Docker publishes ports by editing iptables directly; only Caddy publishes any, so nothing
else is exposed. Check from outside with `nmap -Pn <server>` and confirm only 443 is open.

## 2. Code and production configuration

```bash
sudo mkdir -p /opt/black-mamba && sudo chown "$USER" /opt/black-mamba
git clone <repo-url> /opt/black-mamba && cd /opt/black-mamba
cp .env.example .env.production && chmod 600 .env.production
```

Edit `.env.production`. Every value below is required:

| Variable | Value |
|---|---|
| `APP_ENV` | `production` (turns on the safety checks: strong keys, S3 only, no private-host archiving) |
| `DOMAIN`, `ACME_EMAIL` | your domain and an email address for Let's Encrypt |
| `SECRET_KEY` | `openssl rand -hex 32` |
| `FIELD_ENCRYPTION_KEY` | `python3 -c "import base64,os;print(base64.urlsafe_b64encode(os.urandom(32)).decode())"`. **Never change it later**: 2FA secrets are encrypted with it. |
| `POSTGRES_USER/PASSWORD/DB` | a strong password (`openssl rand -hex 24`) |
| `MINIO_ROOT_USER/PASSWORD` | a strong password |
| `MINIO_KMS_SECRET_KEY` | `echo "bm-prod:$(openssl rand -base64 32)"`. Losing it makes evidence unreadable; back it up offline. |
| `PUBLIC_WEB_URL` | `https://app.example.org` (used in invitation and reset links) |
| `CORS_ORIGINS` | `["https://app.example.org"]` |
| `LLM_PROVIDER` etc. | `anthropic` with `LLM_API_KEY`, `ollama` with `LLM_BASE_URL`, or `fake` to disable the agent |
| `SMTP_*` | optional; without it, admins copy invitation/reset links and share them securely |

`DATABASE_URL`, `REDIS_URL` and the S3 settings are set by `docker-compose.prod.yml`.

Store a copy of `.env.production` (especially `FIELD_ENCRYPTION_KEY` and
`MINIO_KMS_SECRET_KEY`) in your password manager. Backups cannot be used without them.

## 3. First start

```bash
cd /opt/black-mamba
docker compose -f docker-compose.prod.yml --env-file .env.production up -d --build --wait
docker compose -f docker-compose.prod.yml --env-file .env.production ps
curl -fsS https://app.example.org/healthz
```

The first build compiles MinIO from source (MinIO no longer publishes images) and installs
Chromium; expect about 10 minutes. Migrations run automatically when the API starts.

### Bootstrap the operator and the first organisation

```bash
alias bm='docker compose -f /opt/black-mamba/docker-compose.prod.yml --env-file /opt/black-mamba/.env.production exec api blackmamba'
bm create-platform-admin --email you@example.org --name "Your Name"   # prompts for a password
bm create-org --name "Your Team" --admin-email lead@example.org        # prints a one-time invite link
```

1. Sign in as the platform admin and set up 2FA (required before anything else works).
2. Send the org admin their invite link through a secure channel. They accept it, sign in,
   set up 2FA, then invite investigators and reviewers from **Users & invites**.
3. New organisations can apply at `/apply`; you approve or reject them under **Organisations**.

## 4. Backups (daily, encrypted, offsite)

`infrastructure/scripts/backup.sh` runs `verify-all` (audit chains + evidence hashes) first,
then takes a `pg_dump` and a copy of every evidence object, encrypts both with
[age](https://age-encryption.org) using a **public** key, and uploads them with rclone.

1. On your own computer (not the server): `age-keygen -o blackmamba-backup.key`.
   Keep this private key offline (password manager or a hardware-encrypted drive).
   Copy the `age1...` public key it prints.
2. Configure an offsite remote with `rclone config` (Backblaze B2, S3, Hetzner Storage Box…),
   ideally with object lock or versioning so a compromised server cannot delete backups.
3. Create `/etc/black-mamba/backup.env` (`chmod 600`):
   ```bash
   BM_DIR=/opt/black-mamba
   BACKUP_AGE_RECIPIENT=age1...
   BACKUP_REMOTE=b2:blackmamba-backups
   BACKUP_KEEP_DAYS=30
   HEALTHCHECK_URL=https://hc-ping.com/<uuid>   # optional, alerts if a backup fails or is missed
   ```
4. Schedule it: `echo '15 3 * * * root /opt/black-mamba/infrastructure/scripts/backup.sh >> /var/log/bm-backup.log 2>&1' | sudo tee /etc/cron.d/black-mamba-backup`
5. Run it once by hand and check that the files arrive in the remote.

## 5. Restore test (monthly)

On a spare machine with Docker, age, rclone and a checkout of this repo:

```bash
AGE_IDENTITY=~/blackmamba-backup.key BACKUP_REMOTE=b2:blackmamba-backups \
  infrastructure/scripts/restore-test.sh            # latest backup, or pass a timestamp
```

It restores into a throwaway Compose project, verifies every audit hash chain, re-hashes
every evidence object, prints `RESTORE TEST PASSED`, and deletes everything afterwards.
Record the date and result (e.g. in your operations log). For a real disaster recovery,
follow the same steps against the production stack with the production `.env.production`.

## 6. Continuous deployment

`.github/workflows/deploy.yml` deploys `main` after CI passes:

1. Create a deploy user on the server with access to Docker and `/opt/black-mamba`, and an
   SSH key used only for deploys.
2. In GitHub → Settings → Environments, create `production` and add **required reviewers**
   (every deploy waits for a human approval).
3. Add the secrets `DEPLOY_HOST`, `DEPLOY_USER`, `DEPLOY_SSH_KEY`, `DEPLOY_HOST_FINGERPRINT`
   (`ssh-keyscan -t ed25519 <host> | ssh-keygen -lf -`).

The job checks out the exact commit, rebuilds, restarts with `--wait` (health-checked) and runs
`blackmamba verify-all`. To roll back, run the workflow manually from an earlier commit, or
`git checkout <sha>` on the server and re-run the compose command.

## 7. Monitoring

- **Uptime:** point an external monitor (UptimeRobot, healthchecks.io, Uptime Kuma on another
  host) at `https://app.example.org/healthz` and `https://app.example.org/login`.
- **Backups:** `HEALTHCHECK_URL` alerts on failed or missing backups.
- **Errors and logs:** `docker compose -f docker-compose.prod.yml logs -f api worker web`.
  Logs are rotated (5 × 20 MB per service). For alerting, ship them to a log service, or
  add an error tracker such as Sentry; that is not built in yet.
- **Integrity:** the backup run does a full `verify-all` every night. A failure means
  evidence or the audit log changed outside the application: stop and investigate.
- **Updates:** unattended-upgrades patches the OS. Rebuild images monthly
  (`build --pull`) and watch the CI `pip-audit` / `pnpm audit` jobs.

## 8. Security checklist before going live

- [ ] `APP_ENV=production`; the API refuses to start with weak or missing keys.
- [ ] Only 443 (and SSH from your IP) reachable from the internet.
- [ ] Platform admin and every org admin have 2FA on (enforced by the API).
- [ ] `.env.production` is `chmod 600` and backed up offline, together with the age private key.
- [ ] A backup ran and a restore test passed.
- [ ] `LLM_PROVIDER` is a deliberate choice: case metadata and notes are sent to it. Use
      `ollama` if data must not leave your infrastructure.
- [ ] You have a contact and a process for takedown or legal requests about collected evidence.
