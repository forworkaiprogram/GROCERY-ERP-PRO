"""Append-only inventory movement ledger + balance projection.

Stock NEVER changes without an auditable movement row. inventory_balances
is a maintained projection for fast POS reads and is only mutated inside the
same transaction as the movement row.
"""

from __future__ import annotations

import uuid as uuidlib
from decimal import Decimal

from .money import D, qty as qty_str

MOVEMENT_RULES = {
    # movement_type: fixed direction for the rule (1 into stock, -1 out) or
    # None when the caller supplies explicit direction.
    "PURCHASE_RECEIPT": 1,
    "SALE": -1,
    "RETURN_IN": 1,
    "RETURN_OUT": -1,
    "ADJUSTMENT": None,
    "TRANSFER_IN": 1,
    "TRANSFER_OUT": -1,
    "DAMAGED": -1,
    "LOST": -1,
    "COUNT": None,
    "RECONCILIATION": None,
}


class InventoryError(ValueError):
    pass


class InventoryLedger:
    def __init__(self, db):
        self.db = db

    def available_qty(self, tenant_id, branch_id, product_uuid, device_id) -> Decimal:
        """Quantity this device may sell offline.

        When an active offline allocation exists for the device, the allowance
        is min(branch available, allocated_qty) - this prevents two
        disconnected devices from both assuming the full branch stock.
        """
        bal = self.db.query_one(
            "SELECT quantity, reserved_qty FROM inventory_balances"
            " WHERE tenant_id=? AND branch_id=? AND product_uuid=?",
            (tenant_id, branch_id, product_uuid),
        )
        branch_qty = D(bal["quantity"]) - D(bal["reserved_qty"]) if bal else Decimal("0")

        alloc = self.db.query_one(
            "SELECT allocated_qty FROM stock_allocations WHERE tenant_id=? AND"
            " branch_id=? AND product_uuid=? AND device_id=? AND active=1",
            (tenant_id, branch_id, product_uuid, device_id),
        )
        if alloc is None:
            return branch_qty
        allocated = D(alloc["allocated_qty"])
        # The device may not exceed its allocation with its own unacknowledged
        # offline sales: consume the allowance by this device's pending sales.
        pending = self.db.query_one(
            "SELECT COALESCE(SUM(si.quantity), 0) AS sold FROM sale_items si"
            " JOIN sales s ON s.uuid = si.sale_uuid"
            " WHERE s.device_id=? AND s.branch_id=? AND s.sync_state <> 'ACKNOWLEDGED'"
            " AND si.product_uuid=?",
            (device_id, branch_id, product_uuid),
        )
        remaining = allocated - D(pending["sold"])
        capped = allocated if allocated < branch_qty else branch_qty
        return remaining if remaining < capped else capped

    def record_movement(
        self,
        *,
        tenant_id: str,
        branch_id: str,
        product_uuid: str,
        movement_type: str,
        direction: int,
        quantity,
        unit=None,
        warehouse_id=None,
        cost=None,
        batch_no=None,
        expires_at=None,
        reference_type=None,
        reference_uuid=None,
        reason=None,
        created_by=None,
    ) -> dict:
        """Append a movement and update the balance projection. Must be called
        inside an open transaction."""
        if movement_type not in MOVEMENT_RULES:
            raise InventoryError(f"unknown movement type {movement_type!r}")
        quantity = D(quantity)
        if quantity <= 0:
            raise InventoryError("movement quantity must be positive")
        rule_dir = MOVEMENT_RULES[movement_type]
        effective_dir = direction if rule_dir is None else rule_dir
        if effective_dir not in (1, -1):
            raise InventoryError("direction must be 1 or -1")

        movement_uuid = str(uuidlib.uuid4())
        self.db.execute(
            "INSERT INTO inventory_movements (uuid, tenant_id, branch_id, warehouse_id,"
            " product_uuid, movement_type, direction, quantity, unit, cost, batch_no,"
            " expires_at, reference_type, reference_uuid, reason, created_by)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                movement_uuid,
                tenant_id,
                branch_id,
                warehouse_id,
                product_uuid,
                movement_type,
                effective_dir,
                qty_str(quantity),
                unit,
                cost,
                batch_no,
                expires_at,
                reference_type,
                reference_uuid,
                reason,
                created_by,
            ),
        )
        self._apply_to_balance(tenant_id, branch_id, product_uuid, effective_dir * quantity)
        return {"uuid": movement_uuid, "direction": effective_dir}

    def _apply_to_balance(self, tenant_id, branch_id, product_uuid, delta: Decimal) -> None:
        # SQLite has no decimal type; read-modify-write is safe because this
        # always runs inside BEGIN IMMEDIATE (single writer at a time).
        self.db.execute(
            "INSERT OR IGNORE INTO inventory_balances (tenant_id, branch_id,"
            " product_uuid, quantity) VALUES (?,?,?,?)",
            (tenant_id, branch_id, product_uuid, "0"),
        )
        row = self.db.query_one(
            "SELECT quantity FROM inventory_balances WHERE tenant_id=? AND branch_id=?"
            " AND product_uuid=?",
            (tenant_id, branch_id, product_uuid),
        )
        new_qty = D(row["quantity"]) + delta
        if new_qty < 0:
            raise InventoryError(
                f"movement would drive stock below zero for {product_uuid} ({new_qty})"
            )
        self.db.execute(
            "UPDATE inventory_balances SET quantity=? WHERE tenant_id=? AND branch_id=?"
            " AND product_uuid=?",
            (qty_str(new_qty), tenant_id, branch_id, product_uuid),
        )

    def movements_for(self, tenant_id: str, product_uuid: str) -> list:
        rows = self.db.query_all(
            "SELECT * FROM inventory_movements WHERE tenant_id=? AND product_uuid=?"
            " ORDER BY id",
            (tenant_id, product_uuid),
        )
        return [dict(r) for r in rows]

    def movement_payload(self, movement_uuid: str, payload_version: int = 1) -> dict:
        row = self.db.query_one(
            "SELECT * FROM inventory_movements WHERE uuid = ?", (movement_uuid,)
        )
        if row is None:
            raise InventoryError("movement not found")
        data = dict(row)
        data.pop("id")
        return {"schema": "inventory_movement", "version": payload_version, **data}

    def verify_ledger(self, tenant_id: str) -> list:
        """Recompute balances from movements; return drift descriptions."""
        drift = []
        movements = self.db.query_all(
            "SELECT branch_id, product_uuid, direction, quantity"
            " FROM inventory_movements WHERE tenant_id=? ORDER BY id",
            (tenant_id,),
        )
        expected = {}
        for m in movements:
            key = (m["product_uuid"], m["branch_id"])
            expected[key] = expected.get(key, Decimal("0")) + D(m["direction"]) * D(m["quantity"])
        balances = self.db.query_all(
            "SELECT product_uuid, branch_id, quantity FROM inventory_balances WHERE tenant_id=?",
            (tenant_id,),
        )
        actual = {(b["product_uuid"], b["branch_id"]): D(b["quantity"]) for b in balances}
        for key, exp in expected.items():
            act = actual.get(key, Decimal("0"))
            if act != exp:
                drift.append(f"{key[0]}@{key[1]}: projection {act} != ledger {exp}")
        return drift
