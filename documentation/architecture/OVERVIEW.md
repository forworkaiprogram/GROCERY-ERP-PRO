# System Architecture — GROCERY ERP PRO

## 1. Two execution environments

### Local (per Windows installation)
```
┌──────────────────────────────────────────────────────────┐
│ PySide6 native EXE (only business interface)             │
│  UI modules (Login, Dashboard, POS, Modules, Settings,   │
│  Update Center, Super Admin workspace)                   │
│──────────────────────────────────────────────────────────│
│ Local services (Qt-free, unit-testable Python):          │
│  - POS sale engine        - pricing/tax (Decimal)        │
│  - inventory ledger       - double-entry accounting      │
│  - unit conversions       - auth cache                   │
│──────────────────────────────────────────────────────────│
│ Desktop SQLite database (one file per installation)      │
│  - business tables   - outbox_events   - sync checkpoints│
│  - device identity   - entitlement cache - migrations    │
│──────────────────────────────────────────────────────────│
│ Background workers (QThread-owned, UI-never):            │
│  - SyncWorker (outbox drain, backoff, idempotency keys)  │
│  - UpdateWorker (manifest check, staged download)        │
│  - BackupWorker (local scheduled SQLite backups)         │
└──────────────────────────────────────────────────────────┘
```

### Cloud (Django modular monolith + PostgreSQL + Redis + Celery)
```
DRF API (versioned /api/v1)
 ├─ accounts      (JWT auth, MFA flag, Argon2)
 ├─ tenants       (tenant registry, memberships, RLS-compatible schemas)
 ├─ devices       (device enrollment + signed device tokens)
 ├─ synchronization (event ingest, idempotent inbox, acks, conflicts)
 ├─ subscriptions (plans, entitlements, signed snapshots, grace policy)
 ├─ updates       (release management, signed manifests, rollout control)
 └─ audit         (append-only audit trail)
Celery workers: reconciliation, entitlement drafting, rollout expansion
Nginx: TLS termination, rate limiting, static update package serving
```

## 2. Mandatory invariants (enforced in code + tests)

| # | Invariant | Where enforced |
|---|-----------|----------------|
| 1 | One independent SQLite DB + device identity per installation | `desktop/database/`, `desktop/security/device_identity.py` |
| 2 | Sale committed locally with its Outbox event **atomically** | `desktop/business_logic/sale_engine.py` (single SQLite transaction) |
| 3 | Sync never blocks POS | SyncWorker runs in separate thread; UI only reads lightweight status |
| 4 | Idempotency: event replay never duplicates business effects | unique `(tenant_id, event_id)` inbox on server; unique `event_id` outbox |
| 5 | No last-write-wins for stock/money | append-only ledger + server-side conflict detection to `sync_conflicts` |
| 6 | Double entry always balanced, `Decimal` only | `desktop/business_logic/accounting.py` raises on unbalanced; DB CHECK |
| 7 | Posted journal entries immutable (reversals only) | DB triggers + engine refusing UPDATE/DELETE |
| 8 | Tenant isolation: resolve tenant from auth, never from client body | backend serializers ignore client tenant; tests assert cross-tenant 403/404 |
| 9 | Signed entitlement snapshots + signed update manifests (Ed25519) | `desktop/updates/manifest.py`, `desktop/services/entitlements.py` |
| 10 | Subscription expiry never deletes data | server marks tenant `SUSPENDED` only; desktop keeps operating offline per grace policy |

## 3. Synchronization contract (event envelope)

```json
{
  "event_id": "uuid4 (idempotency key)",
  "tenant_id": "uuid",
  "device_id": "uuid",
  "event_type": "sale.created | sale.payment | return.created | inventory.movement |
                 accounting.journal_posted | customer.payment | supplier.payment",
  "payload_version": 1,
  "seq": 41,
  "created_at": "2025-01-15T10:01:00Z",
  "payload": { "...": "..." }
}
```

Server response per event:
```json
{ "event_id": "...", "status": "accepted", "server_seq": 9910 }
{ "event_id": "...", "status": "duplicate", "server_seq": 9907 }
{ "event_id": "...", "status": "conflict", "detail": "inventory BELOW_ZERO",
  "resolution": "manual_review" }
{ "event_id": "...", "status": "rejected", "detail": "schema" }
```

Lifecycle states locally: `PENDING → SENT → ACKNOWLEDGED / CONFLICT / REJECTED`.
Failed events are retried with exponential backoff, never discarded. Events that
end in `CONFLICT` move to the local exception queue and require manual review.

## 4. Multi-device inventory protection

- Each device receives an **offline stock allowance** per product (server-assigned,
  cached, signed with entitlement snapshot).
- Local sale validates availability against `allocated_qty` for the device.
- Server reconciles `inventory.movements`; if movements drive below-zero or
  exceed branch stock, the event is marked `conflict` and stored in
  `sync_conflicts` for authorized review. Original sales are never altered.

## 5. Update system

- Release metadata is canonical-JSON, Ed25519-signed server-side; the public
  key ships with the EXE (private key never leaves server).
- Download → SHA-256 verify → signature verify → schema compatibility check →
  pre-install backup → staged install. Any verification failure rejects the
  package. Details in `documentation/updates/UPDATE_SYSTEM.md`.
