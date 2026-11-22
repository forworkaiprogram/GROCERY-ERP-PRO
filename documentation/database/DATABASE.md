# Database overviews

## Local SQLite (per installation)

- Location: `%LOCALAPPDATA%\GroceryERPPro\` (overrides: `GROCERY_ERP_HOME`;
  non-Windows dev: `~/.local/share/GroceryERPPro`). One file per
  installation; never shared or network-mounted by design.
- Pragmas: WAL, `foreign_keys=ON`, `synchronous=FULL`, busy_timeout 30s;
  raw access only through the lock-serialized `Database` wrapper
  (`BEGIN IMMEDIATE` transactions).
- Migrations: ordered `desktop/database/sql/V*.sql` with a
  `schema_migrations` ledger; each script carries its own version INSERT
  (executescript auto-commits).
- Money is stored as TEXT decimal strings; all arithmetic in Python
  `Decimal` (tables are aggregated in Python; raw SQL `SUM()` over TEXT
  coerces to float and is never used for money).
- Inventory balances derive exclusively from the append-only
  `inventory_movements` ledger; `verify_ledger()` recomputes and detects
  drift (tested).

## Cloud PostgreSQL

- Migrations: Django `0001_initial` migration sets for tenants, accounts,
  devices, synchronization, subscriptions, updates, audit.
- Isolation: every model carries tenant FKs; APIs derive tenant from the
  authenticated principal (see SECURITY.md).
- Money in Postgres is `DecimalField` (numeric), never float.
- Unique constraints: `(tenant, event_id)` inbox idempotency,
  `(app_id, version, channel)` release uniqueness, one active membership
  per (tenant, user).
