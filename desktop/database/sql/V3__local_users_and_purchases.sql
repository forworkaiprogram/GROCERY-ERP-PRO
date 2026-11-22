-- V3: local users (Windows-native authentication) and purchase vouchers.
-- Purchases are real vouchers: goods receipt movements, supplier payable,
-- balanced journal entry, and an outbox purchase.received event -- all in
-- one transaction.
CREATE TABLE IF NOT EXISTS local_users (
    uuid TEXT PRIMARY KEY,
    username TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('admin','manager','cashier','accountant')),
    password_hash TEXT NOT NULL,
    salt TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'ACTIVE'
        CHECK (status IN ('ACTIVE','DISABLED')),
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS purchase_vouchers (
    uuid TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    branch_id TEXT NOT NULL,
    device_id TEXT NOT NULL,
    supplier_uuid TEXT REFERENCES suppliers(uuid),
    total TEXT NOT NULL,
    paid_amount TEXT NOT NULL DEFAULT '0',
    status TEXT NOT NULL DEFAULT 'COMMITTED'
        CHECK (status IN ('COMMITTED','VOID')),
    journal_uuid TEXT REFERENCES journal_entries(uuid),
    created_by TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS purchase_items (
    id INTEGER PRIMARY KEY,
    voucher_uuid TEXT NOT NULL
        REFERENCES purchase_vouchers(uuid) ON DELETE CASCADE,
    product_uuid TEXT NOT NULL REFERENCES products(uuid),
    quantity TEXT NOT NULL,
    unit_cost TEXT NOT NULL,
    line_total TEXT NOT NULL,
    batch_no TEXT,
    expires_at TEXT
);
