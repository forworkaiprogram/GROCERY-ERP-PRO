# Update system guide

## Release lifecycle (server side)

1. A platform administrator (SUPER_ADMIN membership) uploads the release
   package to `POST /api/v1/updates/releases/publish/` (multipart). The
   server computes SHA-256 and size itself.
2. `GET /api/v1/updates/releases/?channel=<stable|beta|internal>` returns
   signed manifests `{"payload":…, "signature":"base64"}`; payloads carry
   every field the desktop verifier requires: app_id, version, build,
   channel, package_url, package_size, sha256, min/max_schema_version,
   required, published_at.
3. Lifecycle: `pause` / `resume` / `withdraw` via
   `/api/v1/updates/releases/manage/` (platform admins only). Paused/withdrawn
   releases vanish from distribution immediately.

## Gradual rollout — honest scope

In this implementation rollout staging is **channel-based** (internal →
beta → stable) and **manual** (pause/withdraw). The per-device
`rollout_percentage` field exists on releases and is stored, but the update
check endpoint is unauthenticated by contract (the desktop Update Center
sends no device credentials), so per-device percentage gating is NOT
enforced server-side. Enforcing it would require device-identified update
checks — listed as remaining work in STATUS.md.

## Desktop verification chain (all mandatory)

1. Ed25519 signature over canonical JSON (public key embedded in EXE).
2. Field validation (app_id, channels, positive size, 64-hex sha256).
3. Anti-downgrade + local schema-range compatibility.
4. Resumable HTTPS download into staging (loopback exception is dev-only
   for tests).
5. Streamed SHA-256 re-verification.
6. Pre-install report (`desktop/updates/preinstall.py`): checksum, disk
   space, DB integrity, FK violations, schema compatibility, pending
   outbox/sales counts, backup target. All gates must pass; `report["ok"]`
   is all-gates.

## Safety properties

- Data directory (`%LOCALAPPDATA%\GroceryERPPro`) is never replaced by
  installs; the Inno Setup script has an intentionally EMPTY
  `[UninstallDelete]` section.
- Upgrades apply versioned local migrations (`V*.sql`) in order; an
  existing database is never re-initialized.
- Pending outbox events and unsynchronized sales survive updates
  (verified in preinstall counts); backups are never deleted by updates.
- Failure recovery: staging copies + integrity probe + rollback copy for
  restores (`desktop/backup/local_backup.py`).
