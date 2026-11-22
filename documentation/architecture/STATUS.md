# Project status — evidence-based

Last updated after the backend build-out. All numbers below come from
commands run in this Linux sandbox (Python 3.12.14, Django 6.1, DRF 3.18,
PySide6 6.12 installed but not executable here — see Limitations).

## Verified in this environment

| Check | Command | Result |
|---|---|---|
| Desktop suite | `python3 -m pytest desktop/tests -p no:cacheprovider --timeout=30 -q` | **44 passed** |
| Backend suite | `cd backend && python3 -m pytest -q` | **27 passed** |
| Django system check | `python3 manage.py check` | no issues |
| Migration sync | `python3 manage.py makemigrations --check --dry-run` | no changes detected |

What the backend tests prove (real HTTP tests against the DRF API):

- Device-token authentication enforced (missing/unknown/expired token → 401).
- Client-claimed `tenant_id`/`device_id` mismatching the authenticated
  device → rejected ack, nothing persisted.
- Idempotent replay: same event twice → `accepted` then `duplicate`; exactly
  one inbox row and one applied effect.
- Integrity quarantine: unbalanced journal and payment-total mismatch →
  `conflict` ack, ConflictRecord preserves the payload, no effect applied.
- Cross-tenant isolation: a device cannot ingest another tenant's event;
  a stranger cannot enroll into a tenant; device listing is membership-scoped.
- Subscription expiry: only subscription lifecycle rows change; devices,
  tokens, and tenant records are untouched; beyond the grace window the
  snapshot serves **no entitlements** (never deletion).
- Entitlement snapshot and update manifest signatures produced by the
  cloud **verify with the real desktop verifier modules** (the backend
  tests import desktop code and check the exact byte-level contract).
- Release publication requires a SUPER_ADMIN membership; tenant admins
  get 403, and a paused release disappears from distribution.
- Device enrollment/revocation/refresh semantics (revoked tokens die
  immediately).

What the desktop tests prove: atomic sale+outbox+journal commits, offline
operation without any cloud, rollback on failure, credit/stock guards,
two-device allocation caps, ticket-lock style concurrency safety, sync
replay idempotency, conflict/refusal states never overridden, exponential
backoff, Ed25519 manifest verification (valid/tampered/wrong-key/missing),
resumable Range downloads over a live socket, entitlement grace/lite
de-escalation (never deleting data), backup/restore roundtrip, preinstall
safety report gates, receipt/ESC-POS rendering.

## Known limitations (honest)

1. **The EXE itself was not built or run here.** This sandbox is Linux,
   non-root, without Windows. PySide6 is installed but cannot initialize Qt
   (missing system GUI libraries). The UI code paths are kept thin and all
   business logic is Qt-free and covered by tests, but per rule 26 the
   packaged executable must be built and walked through on Windows
   (see `desktop/packaging/PACKAGING.md`) before any customer use.
2. **Docker stack not executed here** (no OS-level containers/runtime).
   Compose, Dockerfile, and Nginx configs are written and reviewed but
   `docker compose up` was not run in this sandbox.
3. **Release signing keys are dev placeholders**: the committed
   `cloud_ed25519.pub` corresponds to keys generated during development
   and will be REPLACED at first provisioning
   (`scripts/generate_signing_keys.py`). Treat the current published key
   as non-trustworthy for production.
4. **Update-check gradual rollout**: channel-based staging and manual
   pause/withdraw only; per-device percentage gating needs device-identified
   update checks (documented in UPDATES.md).
5. **Central effects are minimal**: accepted sync events are recorded with
   server sequencing and audited; materialized central ledgers (products,
   balances) for cross-device reconciliation reports and the full Super
   Admin dashboard screens are remaining work (Celery beat + tasks exist;
   deep reconciliation logic is next).
6. **ERP module coverage**: POS/sales, pricing, units, inventory ledger,
   double-entry accounting, returns plumbing, sync, updates, entitlements
   have working tested engines. Purchasing/HR/payroll full modules, advanced
   reports, Arabic UI translations, MFA flows, Suspended-sales UI, dashboards
   and the remaining screen work (functions currently surface via
   read-only data screens) are later-phase work — nothing is stubbed to
   pretend otherwise.
7. **UI is usable but not polished**: navigation + POS + placeholder data
   screens exist; the placeholder screens are intentionally read-only
   real-data views (no fake data), not finished module UIs.
8. **No git repository/remote initialized in this workspace**; delivery to
   a GitHub repository requires the user to name one (none was selected).

## Remaining production-readiness tasks

- Windows build machine run-through of packaging runbook + acceptance tests.
- `docker compose up` verification on a Linux host with PostgreSQL/Redis;
  ZAP baseline scan; pip-audit/bandit in CI.
- OpenAPI schema endpoint (drf-spectacular).
- Device-identified update checks for percentage rollout gating.
- Celery reconciliation task implementation over inbox events.
- Super Admin screens in the EXE hitting the platform APIs; MFA enrollment.
- Full purchasing/HR/payroll/report modules and localization files.
