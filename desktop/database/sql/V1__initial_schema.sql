-- GROCERY ERP PRO local schema, version 1.
-- Monetary values are TEXT storing decimal strings (SQLite has no Decimal;
-- all arithmetic happens in Python with `decimal.Decimal`).

CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS device_identity (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    device_id TEXT NOT NULL UNIQUE,
    device_name TEXT NOT NULL,
    tenant_id TEXT,
    branch_id TEXT,
    warehouse_id TEXT,
    registration_status TEXT NOT NULL DEFAULT 'PENDING',
    registered_at TEXT,
    revoked INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS app_config (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS categories (
    uuid TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    parent_uuid TEXT REFERENCES categories(uuid) ON DELETE SET NULL,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS units (
    uuid TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    code TEXT NOT NULL UNIQUE,             -- CARTON, PACK, PIECE, KG, G, L, ML, BOX, BOTTLE, BUNDLE
    dimension TEXT NOT NULL CHECK (dimension IN ('COUNT','MASS','VOLUME')),
    base_ratio REAL NOT NULL DEFAULT 1.0,
    is_base INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS unit_conversions (
    uuid TEXT PRIMARY KEY,
    from_unit TEXT NOT NULL REFERENCES units(uuid) ON DELETE CASCADE,
    to_unit TEXT NOT NULL REFERENCES units(uuid) ON DELETE CASCADE,
    numerator INTEGER NOT NULL,            -- exact rational: from_value * numerator
    denominator INTEGER NOT NULL,          --   / denominator = to_value
    UNIQUE (from_unit, to_unit),
    CHECK (denominator > 0 AND numerator > 0)
);

CREATE TABLE IF NOT EXISTS products (
    uuid TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    sku TEXT NOT NULL,
    name TEXT NOT NULL,
    name_ar TEXT,
    description TEXT,
    category_uuid TEXT REFERENCES categories(uuid) ON DELETE SET NULL,
    brand TEXT,
    supplier_uuid TEXT,
    image_path TEXT,
    cost TEXT NOT NULL DEFAULT '0',
    price TEXT NOT NULL DEFAULT '0',
    wholesale_price TEXT NOT NULL DEFAULT '0',
    min_price TEXT NOT NULL DEFAULT '0',
    default_unit TEXT REFERENCES units(uuid),
    tax_rate_bps INTEGER NOT NULL DEFAULT 0,     -- basis points, configurable
    track_expiration INTEGER NOT NULL DEFAULT 0,
    track_batches INTEGER NOT NULL DEFAULT 0,
    min_stock TEXT NOT NULL DEFAULT '0',
    max_stock TEXT NOT NULL DEFAULT '0',
    reorder_level TEXT NOT NULL DEFAULT '0',
    status TEXT NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE','INACTIVE')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (tenant_id, sku)
);
CREATE INDEX IF NOT EXISTS idx_products_name ON products(name);

CREATE TABLE IF NOT EXISTS product_barcodes (
    id INTEGER PRIMARY KEY,
    product_uuid TEXT NOT NULL REFERENCES products(uuid) ON DELETE CASCADE,
    barcode TEXT NOT NULL UNIQUE,
    unit TEXT REFERENCES units(uuid),
    pack_qty TEXT NOT NULL DEFAULT '1'
);

CREATE TABLE IF NOT EXISTS customers (
    uuid TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    name TEXT NOT NULL,
    phone TEXT,
    address TEXT,
    group_name TEXT,
    credit_limit TEXT NOT NULL DEFAULT '0',
    balance TEXT NOT NULL DEFAULT '0',         -- positive = customer owes us
    loyalty_points TEXT NOT NULL DEFAULT '0',
    discount_bps INTEGER NOT NULL DEFAULT 0,
    notes TEXT,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS suppliers (
    uuid TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    name TEXT NOT NULL,
    phone TEXT,
    address TEXT,
    credit_limit TEXT NOT NULL DEFAULT '0',
    balance TEXT NOT NULL DEFAULT '0',         -- positive = we owe supplier
    payment_terms_days INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Append-only inventory movement ledger. Stock balances are derivable; the
-- inventory_balances table is a maintained projection for fast POS reads.
CREATE TABLE IF NOT EXISTS inventory_movements (
    id INTEGER PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    uuid TEXT NOT NULL UNIQUE,                 -- idempotency key for the movement
    branch_id TEXT NOT NULL,
    warehouse_id TEXT,
    product_uuid TEXT NOT NULL REFERENCES products(uuid),
    movement_type TEXT NOT NULL CHECK (movement_type IN
        ('PURCHASE_RECEIPT','SALE','RETURN_IN','RETURN_OUT','ADJUSTMENT',
         'TRANSFER_IN','TRANSFER_OUT','DAMAGED','LOST','COUNT','RECONCILIATION')),
    direction INTEGER NOT NULL CHECK (direction IN (1,-1)),
    quantity TEXT NOT NULL,
    unit TEXT REFERENCES units(uuid),
    cost TEXT,
    batch_no TEXT,
    expires_at TEXT,
    reference_type TEXT,
    reference_uuid TEXT,
    reason TEXT,
    created_by TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_moves_product ON inventory_movements(product_uuid, branch_id, created_at);

CREATE TABLE IF NOT EXISTS inventory_balances (
    tenant_id TEXT NOT NULL,
    branch_id TEXT NOT NULL,
    product_uuid TEXT NOT NULL REFERENCES products(uuid) ON DELETE CASCADE,
    quantity TEXT NOT NULL DEFAULT '0',
    reserved_qty TEXT NOT NULL DEFAULT '0',
    PRIMARY KEY (tenant_id, branch_id, product_uuid)
);

CREATE TABLE IF NOT EXISTS stock_allocations (
    id INTEGER PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    branch_id TEXT NOT NULL,
    product_uuid TEXT NOT NULL REFERENCES products(uuid) ON DELETE CASCADE,
    device_id TEXT NOT NULL,
    allocated_qty TEXT NOT NULL DEFAULT '0',
    max_offline_sell_qty TEXT NOT NULL DEFAULT '0',
    active INTEGER NOT NULL DEFAULT 1,
    UNIQUE (branch_id, product_uuid, device_id)
);

CREATE TABLE IF NOT EXISTS sales (
    uuid TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    branch_id TEXT NOT NULL,
    device_id TEXT NOT NULL,
    cashier_id TEXT NOT NULL,
    invoice_no TEXT NOT NULL,
    sale_no INTEGER NOT NULL,                  -- per-device monotonic sequence
    customer_uuid TEXT REFERENCES customers(uuid),
    subtotal TEXT NOT NULL,
    discount_total TEXT NOT NULL DEFAULT '0',
    tax_total TEXT NOT NULL DEFAULT '0',
    total TEXT NOT NULL,
    cost_total TEXT NOT NULL DEFAULT '0',
    status TEXT NOT NULL DEFAULT 'COMMITTED'
        CHECK (status IN ('COMMITTED','SUSPENDED','RETURNED','PARTIALLY_RETURNED','VOID')),
    sync_state TEXT NOT NULL DEFAULT 'PENDING'
        CHECK (sync_state IN ('PENDING','SENT','ACKNOWLEDGED','CONFLICT','REJECTED')),
    priced_snapshot TEXT NOT NULL,             -- JSON: prices/taxes/discounts at sale time
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (tenant_id, device_id, sale_no)
);

CREATE TABLE IF NOT EXISTS sale_items (
    id INTEGER PRIMARY KEY,
    sale_uuid TEXT NOT NULL REFERENCES sales(uuid) ON DELETE CASCADE,
    product_uuid TEXT NOT NULL REFERENCES products(uuid),
    unit TEXT REFERENCES units(uuid),
    quantity TEXT NOT NULL,
    unit_price TEXT NOT NULL,                  -- snapshot
    discount TEXT NOT NULL DEFAULT '0',
    tax_rate_bps INTEGER NOT NULL DEFAULT 0,
    tax_amount TEXT NOT NULL DEFAULT '0',
    line_total TEXT NOT NULL,
    unit_cost TEXT NOT NULL DEFAULT '0',
    batch_no TEXT
);

CREATE TABLE IF NOT EXISTS payments (
    id INTEGER PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    uuid TEXT NOT NULL UNIQUE,                 -- idempotency key
    payment_type TEXT NOT NULL CHECK (payment_type IN
        ('SALE','CUSTOMER_PAYMENT','SUPPLIER_PAYMENT','REFUND','EXPENSE')),
    reference_uuid TEXT,
    method TEXT NOT NULL CHECK (method IN ('CASH','CARD','CREDIT','WALLET','BANK','OTHER')),
    amount TEXT NOT NULL,
    received_at TEXT NOT NULL DEFAULT (datetime('now')),
    sync_state TEXT NOT NULL DEFAULT 'PENDING',
    meta TEXT
);

CREATE TABLE IF NOT EXISTS returns (
    uuid TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    sale_uuid TEXT NOT NULL REFERENCES sales(uuid),
    branch_id TEXT NOT NULL,
    device_id TEXT NOT NULL,
    reason TEXT,
    total TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'COMMITTED' CHECK (status IN ('COMMITTED','VOID')),
    approved_by TEXT,
    priced_snapshot TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS return_items (
    id INTEGER PRIMARY KEY,
    return_uuid TEXT NOT NULL REFERENCES returns(uuid) ON DELETE CASCADE,
    sale_item_id INTEGER REFERENCES sale_items(id),
    product_uuid TEXT NOT NULL REFERENCES products(uuid),
    quantity TEXT NOT NULL,
    unit_price TEXT NOT NULL,
    line_total TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS cash_sessions (
    uuid TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    branch_id TEXT NOT NULL,
    device_id TEXT NOT NULL,
    cashier_id TEXT NOT NULL,
    opened_at TEXT NOT NULL DEFAULT (datetime('now')),
    closed_at TEXT,
    opening_balance TEXT NOT NULL DEFAULT '0',
    closing_balance TEXT,
    expected_balance TEXT,
    discrepancy TEXT,
    status TEXT NOT NULL DEFAULT 'OPEN' CHECK (status IN ('OPEN','CLOSED'))
);

-- Double-entry accounting events (locally provisional events; confirmed entries
-- are posted centrally after sync). Every entry must balance.
CREATE TABLE IF NOT EXISTS journal_entries (
    uuid TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    entry_no TEXT NOT NULL,
    entry_date TEXT NOT NULL DEFAULT (date('now')),
    memo TEXT,
    source_type TEXT NOT NULL,                 -- 'SALE','EXPENSE','PAYMENT','ADJUSTMENT','OPENING'
    source_uuid TEXT,
    status TEXT NOT NULL DEFAULT 'LOCALLY_PROVISIONAL'
        CHECK (status IN ('LOCALLY_PROVISIONAL','CENTRALLY_POSTED','REVERSED')),
    reversal_of TEXT REFERENCES journal_entries(uuid),
    sync_state TEXT NOT NULL DEFAULT 'PENDING',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (tenant_id, entry_no)
);

CREATE TABLE IF NOT EXISTS journal_lines (
    id INTEGER PRIMARY KEY,
    entry_uuid TEXT NOT NULL REFERENCES journal_entries(uuid) ON DELETE CASCADE,
    account_code TEXT NOT NULL REFERENCES accounts(code),
    debit TEXT NOT NULL DEFAULT '0' CHECK (debit >= '0'),
    credit TEXT NOT NULL DEFAULT '0' CHECK (credit >= '0'),
    CHECK (debit <> credit OR debit = '0')
);

CREATE TABLE IF NOT EXISTS accounts (
    code TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    name_ar TEXT,
    type TEXT NOT NULL CHECK (type IN ('ASSET','LIABILITY','EQUITY','REVENUE','EXPENSE')),
    is_cash INTEGER NOT NULL DEFAULT 0,
    parent_code TEXT REFERENCES accounts(code),
    is_system INTEGER NOT NULL DEFAULT 0      -- system accounts cannot be deleted
);

CREATE TABLE IF NOT EXISTS expense_vouchers (
    uuid TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    category TEXT NOT NULL,
    amount TEXT NOT NULL,
    paid_from_account TEXT NOT NULL REFERENCES accounts(code),
    paid_to TEXT,
    payment_method TEXT NOT NULL DEFAULT 'CASH',
    voucher_date TEXT NOT NULL DEFAULT (date('now')),
    approved_by TEXT,
    attachment_paths TEXT,
    journal_uuid TEXT REFERENCES journal_entries(uuid),
    sync_state TEXT NOT NULL DEFAULT 'PENDING',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Synchronization
CREATE TABLE IF NOT EXISTS outbox_events (
    id INTEGER PRIMARY KEY,
    event_id TEXT NOT NULL UNIQUE,             -- uuid4 idempotency key
    tenant_id TEXT NOT NULL,
    device_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    payload_version INTEGER NOT NULL DEFAULT 1,
    seq INTEGER NOT NULL,                      -- per-device monotonic event sequence
    payload TEXT NOT NULL,                     -- canonical JSON
    references_sale TEXT,
    state TEXT NOT NULL DEFAULT 'PENDING'
        CHECK (state IN ('PENDING','SENT','ACKNOWLEDGED','CONFLICT','REJECTED')),
    attempts INTEGER NOT NULL DEFAULT 0,
    next_attempt_at TEXT,
    last_error TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    acknowledged_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_outbox_state ON outbox_events(state, next_attempt_at);

CREATE TABLE IF NOT EXISTS sync_checkpoints (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    last_server_seq INTEGER NOT NULL DEFAULT 0,
    last_sync_at TEXT,
    last_successful_sync_at TEXT
);

CREATE TABLE IF NOT EXISTS sync_logs (
    id INTEGER PRIMARY KEY,
    at TEXT NOT NULL DEFAULT (datetime('now')),
    level TEXT NOT NULL,
    message TEXT NOT NULL,
    event_id TEXT
);

CREATE TABLE IF NOT EXISTS sync_conflicts (
    id INTEGER PRIMARY KEY,
    event_id TEXT NOT NULL UNIQUE,
    event_type TEXT NOT NULL,
    detail TEXT NOT NULL,
    payload TEXT NOT NULL,
    received_at TEXT NOT NULL DEFAULT (datetime('now')),
    status TEXT NOT NULL DEFAULT 'OPEN' CHECK (status IN ('OPEN','RESOLVED')),
    resolved_by TEXT,
    resolution TEXT
);

-- Security / entitlement caches
CREATE TABLE IF NOT EXISTS cached_permissions (
    user_id TEXT NOT NULL,
    role TEXT NOT NULL,
    permissions TEXT NOT NULL,                 -- JSON list
    granted_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    PRIMARY KEY (user_id, role)
);

CREATE TABLE IF NOT EXISTS entitlement_cache (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    plan TEXT NOT NULL,
    entitlements TEXT NOT NULL,                -- JSON mapping
    signature TEXT NOT NULL,
    signed_at TEXT NOT NULL,
    valid_until TEXT NOT NULL,
    verified INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS auth_cache (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    user_id TEXT NOT NULL,
    username TEXT NOT NULL,
    display_name TEXT,
    role TEXT NOT NULL,
    branch_id TEXT,
    token_hash TEXT NOT NULL,                  -- hash of the access token, never plaintext
    token_expires_at TEXT NOT NULL,
    offline_until TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS update_status (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    current_version TEXT NOT NULL,
    current_schema_version INTEGER NOT NULL,
    last_check_at TEXT,
    available_version TEXT,
    available_manifest TEXT,                   -- verified signed manifest JSON
    download_state TEXT NOT NULL DEFAULT 'IDLE'
        CHECK (download_state IN ('IDLE','DOWNLOADING','STAGED','FAILED')),
    staged_path TEXT,
    staged_checksum TEXT,
    last_error TEXT,
    last_successful_install TEXT
);

CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY,
    at TEXT NOT NULL DEFAULT (datetime('now')),
    user_id TEXT,
    action TEXT NOT NULL,
    target_type TEXT,
    target_uuid TEXT,
    detail TEXT
);

CREATE TABLE IF NOT EXISTS notifications (
    id INTEGER PRIMARY KEY,
    at TEXT NOT NULL DEFAULT (datetime('now')),
    category TEXT NOT NULL,
    severity TEXT NOT NULL DEFAULT 'INFO' CHECK (severity IN ('INFO','WARNING','CRITICAL')),
    message TEXT NOT NULL,
    target_type TEXT,
    target_uuid TEXT,
    read INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS expense_categories (
    name TEXT PRIMARY KEY,
    name_ar TEXT
);
