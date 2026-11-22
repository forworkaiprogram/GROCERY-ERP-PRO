# Cloud deployment guide

## Prerequisites

- Linux host with Docker + Docker Compose v2.
- DNS name + TLS certificate/key (fullchain.pem, privkey.pem) at
  `infrastructure/nginx/certs/`.
- Generated signing keys (see below).

## Steps

1. **Secrets** (never in git):
   ```
   cp .env.example .env         # fill POSTGRES_*, DJANGO_ALLOWED_HOSTS
   mkdir -p secrets
   python scripts/generate_signing_keys.py \
       --server-keys-dir secrets/keys \
       --desktop-pub desktop/security/public_keys/cloud_ed25519.pub
   cp secrets/keys/update_signing_key.pem secrets/update_signing_key.pem
   cp secrets/keys/entitlement_signing_key.pem secrets/entitlement_signing_key.pem
   printf '%s' "$(python -c 'import secrets;print(secrets.token_urlsafe(64))')" \
       > secrets/django_secret_key.txt
   ```
   Rotate `cloud_ed25519.pub` in the desktop tree ONLY as a deliberate
   key-rotation release.

2. **Start the stack**
   ```
   docker compose up -d --build
   docker compose exec backend python manage.py createsuperuser
   ```

3. **Backups** — schedule `infrastructure/backups/backup_postgres.sh`
   (cron), and verify by restoring to a scratch database after the first
   run. A backup is not verified until restored.

4. **Smoke verification** (do not skip)
   - `GET https://<host>/api/v1/health/` must answer `{"status": "ok"}`.
   - `POST https://<host>/api/v1/auth/login/` with JSON
     `{"username": "...", "password": "..."}` must return a token and
     memberships.

5. **Device enrollment**: log in as a tenant owner, enroll each POS device
   (`POST /api/v1/devices/enroll/`), then configure the issued device token
   + tenant UUID into the EXE. The EXE then syncs and fetches entitlement
   snapshots with its own token.

## Updating the backend

`git pull && docker compose up -d --build` (migrations run in the backend
entrypoint). Data volumes (pgdata, update-storage) persist.

## Update-package storage

Release packages uploaded through the publish API live in the
`update_storage` volume; Nginx serves them read-only at
`/api/v1/updates/packages/` with `autoindex off`. Packages remain gated by
the signed manifest — a served file cannot make a device install it
without a signature match.
