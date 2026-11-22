"""Local repositories for POS-critical entities (products, customers)."""

from __future__ import annotations


class ProductRepository:
    def __init__(self, db):
        self.db = db

    def get(self, tenant_id: str, product_uuid: str) -> dict | None:
        row = self.db.query_one(
            "SELECT * FROM products WHERE tenant_id=? AND uuid=?",
            (tenant_id, product_uuid),
        )
        return dict(row) if row else None

    def by_sku(self, tenant_id: str, sku: str) -> dict | None:
        row = self.db.query_one(
            "SELECT * FROM products WHERE tenant_id=? AND sku=?", (tenant_id, sku)
        )
        return dict(row) if row else None

    def by_barcode(self, tenant_id: str, barcode: str) -> dict | None:
        row = self.db.query_one(
            "SELECT p.* FROM products p JOIN product_barcodes b ON b.product_uuid=p.uuid"
            " WHERE p.tenant_id=? AND b.barcode=?",
            (tenant_id, barcode),
        )
        return dict(row) if row else None

    def search(self, tenant_id: str, term: str, limit: int = 25) -> list[dict]:
        like = f"%{term}%"
        rows = self.db.query_all(
            "SELECT * FROM products WHERE tenant_id=? AND status='ACTIVE'"
            " AND (name LIKE ? OR sku LIKE ?) ORDER BY name LIMIT ?",
            (tenant_id, like, like, limit),
        )
        return [dict(r) for r in rows]

    def low_stock(self, tenant_id: str) -> list[dict]:
        rows = self.db.query_all(
            "SELECT p.uuid, p.name, p.reorder_level, SUM(b.quantity) AS on_hand"
            " FROM products p JOIN inventory_balances b ON b.product_uuid=p.uuid"
            " WHERE p.tenant_id=? GROUP BY p.uuid, p.name, p.reorder_level"
            " HAVING on_hand <= p.reorder_level",
            (tenant_id,),
        )
        return [dict(r) for r in rows]

    def insert(self, p: dict) -> None:
        self.db.execute(
            "INSERT INTO products (uuid, tenant_id, sku, name, name_ar, category_uuid,"
            " brand, supplier_uuid, cost, price, wholesale_price, min_price,"
            " default_unit, tax_rate_bps, track_expiration, track_batches, min_stock,"
            " max_stock, reorder_level, status) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                p["uuid"], p["tenant_id"], p["sku"], p["name"], p.get("name_ar"),
                p.get("category_uuid"), p.get("brand"), p.get("supplier_uuid"),
                str(p.get("cost", "0")), str(p.get("price", "0")),
                str(p.get("wholesale_price", "0")), str(p.get("min_price", "0")),
                p.get("default_unit"), int(p.get("tax_rate_bps", 0)),
                int(p.get("track_expiration", 0)), int(p.get("track_batches", 0)),
                str(p.get("min_stock", "0")), str(p.get("max_stock", "0")),
                str(p.get("reorder_level", "0")), p.get("status", "ACTIVE"),
            ),
        )

    def add_barcode(self, product_uuid: str, barcode: str, unit=None, pack_qty="1") -> None:
        self.db.execute(
            "INSERT OR IGNORE INTO product_barcodes (product_uuid, barcode, unit, pack_qty)"
            " VALUES (?,?,?,?)",
            (product_uuid, barcode, unit, pack_qty),
        )


class CustomerRepository:
    def __init__(self, db):
        self.db = db

    def get(self, tenant_id: str, customer_uuid: str) -> dict | None:
        row = self.db.query_one(
            "SELECT * FROM customers WHERE tenant_id=? AND uuid=?",
            (tenant_id, customer_uuid),
        )
        return dict(row) if row else None

    def insert(self, c: dict) -> None:
        self.db.execute(
            "INSERT INTO customers (uuid, tenant_id, name, phone, address, group_name,"
            " credit_limit, discount_bps, notes) VALUES (?,?,?,?,?,?,?,?,?)",
            (
                c["uuid"], c["tenant_id"], c["name"], c.get("phone"),
                c.get("address"), c.get("group_name"),
                str(c.get("credit_limit", "0")), int(c.get("discount_bps", 0)),
                c.get("notes"),
            ),
        )

    def add_balance(self, tenant_id: str, customer_uuid: str, delta) -> None:
        row = self.db.query_one(
            "SELECT balance FROM customers WHERE tenant_id=? AND uuid=?",
            (tenant_id, customer_uuid),
        )
        from .money import D, money

        new_bal = D(row["balance"]) + D(delta)
        self.db.execute(
            "UPDATE customers SET balance=? WHERE tenant_id=? AND uuid=?",
            (money(new_bal), tenant_id, customer_uuid),
        )


class SupplierRepository:
    def __init__(self, db):
        self.db = db

    def insert(self, s: dict) -> None:
        self.db.execute(
            "INSERT INTO suppliers (uuid, tenant_id, name, phone, address, credit_limit,"
            " payment_terms_days) VALUES (?,?,?,?,?,?,?)",
            (
                s["uuid"], s["tenant_id"], s["name"], s.get("phone"),
                s.get("address"), str(s.get("credit_limit", "0")),
                int(s.get("payment_terms_days", 0)),
            ),
        )
