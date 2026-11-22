# Project status — evidence-based

Last updated after the backend build-out. All numbers below come from
commands run in this Linux sandbox (Python 3.12.14, Django 6.1, DRF 3.18,
PySide6 6.12 installed but not executable here — see Limitations).

## Verified in this environment

| Check | Command | Result |
|---|---|---|
| Desktop suite | `LD_LIBRARY_PATH=$QT_LIBS QT_QPA_PLATFORM=offscreen python3 -m pytest desktop/tests -p no:cacheprovider -q` | **66 passed** (64 Qt-free engine tests + 2 offscreen-Qt end-to-end smoke) |
| UI static analysis | `python3 -m pyflakes desktop/ui desktop/app` | clean (new Phase 2 files) |
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
6. **ERP module coverage (updated after UI Phase 2)**: the Arabic-first
   shell is rebuilt as a real ERP workspace modeled on a reference
   system and wired to the tested engines:
   - Sidebar navigation like the reference app (`dashboard pos, منتجات،
     مبيعات، مشتريات، مرتجعات، عملاء، موردون، ديون، جرد، ورديات،
     محاسبة، مصروفات، تقارير، مستخدمون، مزامنة، تحديثات، اشتراك،
     إعدادات`) — all backed by real engines; HR stays an honest notice.
   - Local login dialog (PBKDF2 LocalAuth, offline-capable) with an
     `admin/admin123` seed and a first-login warning until changed.
   - RBAC: admin / manager / cashier / accountant see different menus;
     cashier lands straight on POS.
   - POS: Arabic RTL, customer picker (with balance/hint), +/− cart
     editing, tax-total display, payment method, quick-cash with
     change, F2/F12, current-shift display, local commit + outbox.
   - Sales: invoice list, item viewer, text receipt preview.
   - Purchases: full receiving dialog → movements + balanced journal +
     supplier balance + outbox, listed with paid/credit split.
   - Returns: invoice lookup, remaining-quantity enforcement, real
     `return_sale` (refund journal + stock restore + `sale.returned`).
   - Debts: filtered debtors, customer payment posting (journal +
     balance + payment event).
   - Stocktake: expected/counted grid, `submit_count` adjustments.
   - Shifts: open/close with Decimal cash summary and discrepancy.
   - Users (admin only): create/reset/disable through LocalAuth with
     last-active-admin protection.
   - Settings: store config, backup create/restore (verified sidecar),
     password change, theme (light/dark) + language.
   - Light/dark QSS theme with explicit palettes (fixes the earlier
     black-window class of bugs), theme toggle + Ctrl+K palette.
7. **Qt runs headless in this sandbox** (offscreen platform); the
   end-to-end business-flow smoke test (login → purchase → POS sale →
   return → stocktake → debt payment → shift close → backup → theme)
   runs green here. The packaged EXE must still be validated on real
   Windows per rule 26.

8. **Delivery**: the repository is published at https://github.com/forworkaiprogram/GROCERY-ERP-PRO (main branch). Sandbox-native git push is blocked by the session proxy, so commits are delivered through the GitHub REST Git Data API.

## Remaining production-readiness tasks

- Windows build machine run-through of packaging runbook + acceptance tests.
- `docker compose up` verification on a Linux host with PostgreSQL/Redis;
  ZAP baseline scan; pip-audit/bandit in CI.
- OpenAPI schema endpoint (drf-spectacular).
- Device-identified update checks for percentage rollout gating.
- Celery reconciliation task implementation over inbox events.
- Super Admin screens in the EXE hitting the platform APIs; MFA enrollment.
- Full purchasing/HR/payroll/report modules and localization files.
