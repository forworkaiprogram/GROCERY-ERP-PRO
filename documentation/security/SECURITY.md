# Security notes

## Implemented and verified

- **Argon2** password hashing (Django `PASSWORD_HASHERS`).
- **Ed25519-signed artifacts**: update manifests and entitlement snapshots;
  desktop verifies via embedded public key. Tampered/wrong-key/missing-field
  cases are covered by tests on BOTH sides (desktop
  `test_updates_signing.py`, backend `test_updates_release.py` — the backend
  test actually invokes the desktop's verifier module).
- **Tenant isolation by construction**: tenant context is resolved ONLY from
  the authenticated principal (device token or user membership). Cross-tenant
  sync payloads, enrollments, device listings, snapshots, and payment
  declarations are covered by tests on both sides.
- **Token hygiene**: opaque device/user tokens stored as SHA-256 only;
  revocation is immediate and enforced (`test_revoked_device_tokens_stop_working`).
- **Idempotent ingest**: unique constraint + replay check prevents duplicate
  financial effects (tested).
- **Integrity gates**: unbalanced journals and payment-total mismatches are
  quarantined as conflicts, never applied (tested).
- **Rate limiting**: anon/user throttles globally; a device-scoped throttle
  (`DeviceRateThrottle`, 600/min) for device-principal requests.
- **Security headers** in Django settings (nosniff, X-Frame-Options DENY,
  cookie security in prod) and Nginx (HSTS, TLS 1.2+, server tokens off).
- **Secrets**: `.env`/Docker-secrets only; secret-like values are never in
  source. Desktop local secrets via DPAPI on Windows
  (`desktop/security/secrets.py`).

## Required before production (not yet run in this environment)

- OWASP ZAP baseline scan of a deployed HTTPS stack.
- pip-audit/bandit runs on CI.
- MFA enforcement for platform administrators (MFA fields exist on User;
  the enrollment/login flow is not built — documented honestly).
- PostgreSQL Row-Level Security as a defense-in-depth layer.
