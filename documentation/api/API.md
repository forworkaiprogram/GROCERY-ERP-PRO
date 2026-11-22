# API notes (v1)

Base path: `/api/v1/`. All responses are JSON (DRF). Endpoints are
moderate-scale and intentionally hand-rolled rather than generated; a
drf-spectacular OpenAPI schema endpoint is remaining work (STATUS.md).

## Authentication modes

| Mode | Header | Used by |
|---|---|---|
| Device token | `Authorization: Device <token>` | sync ingest, entitlement snapshot, update attempts, device whoami/refresh |
| User bearer | `Authorization: Bearer <token>` | login/me, device enrollment/list/revoke, subscription status, payment declaration |
| None | — | health, releases list (signed-manifest distribution), login |

Tokens are opaque; servers store only SHA-256 hashes. Passwords use Argon2.

## Endpoints

| Method/Path | Purpose |
|---|---|
| GET `/health/` | liveness |
| POST `/auth/login/` | username+password → bearer token + memberships |
| GET `/auth/me/` | current principal, platform-admin flag |
| POST `/devices/enroll/` | register a device (requires active membership) → device_uuid + token |
| POST `/devices/refresh-token/` | rotate device token (old one revoked) |
| GET `/devices/whoami/` | device's own identity and tenant binding |
| GET/POST `/devices/` | list / revoke tenant devices (membership-scoped) |
| POST `/sync/events/` | idempotent batch ingest with acks (see SYNC.md) |
| GET `/subscriptions/snapshot/` | signed entitlement snapshot (device) |
| GET `/subscriptions/status/` | tenant subscription status (membership-scoped) |
| POST `/subscriptions/payments/declare/` | declare manual payment (PENDING) |
| GET `/updates/releases/` | signed release-manifest list |
| POST `/updates/releases/publish/` | upload+publish (SUPER_ADMIN only) |
| POST `/updates/releases/manage/` | pause/resume/withdraw (SUPER_ADMIN only) |
| POST `/updates/attempts/` | device update-outcome reports |

## Errors

Standard DRF error bodies. Authentication failures are 401 with a detail
message; tenant-scope violations surface as validation/validation errors or
404 per endpoint (never cross-tenant payloads).
