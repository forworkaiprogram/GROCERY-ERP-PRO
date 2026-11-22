"""Purchasing: goods-receipt vouchers.

One transaction records: the voucher + items, a PURCHASE_RECEIPT movement
per product line (append-only ledger), the supplier payable balance, a
balanced journal entry (DR Inventory 1200, CR AP 2000 for the credit part,
CR 1000 for the paid part), payment rows, and one purchase.received
outbox event.
"""

from __future__ import annotations

import uuid as uuidlib
from decimal import Decimal

from .accounting import AccountingEngine, AccountingError
from .inventory import InventoryLedger, InventoryError
from .money import D, money
from ..synchronization.outbox import Outbox


class PurchaseError(ValueError):
    pass


def receive_purchase(db, *, tenant_id: str, branch_id: str, device_id: str,
                     supplier_uuid: str | None, items: list[dict],
                     paid_amount, payment_method: str = "CASH",
                     created_by: str | None = None,
                     accounting: AccountingEngine | None = None,
                     ledger: InventoryLedger | None = None,
                     outbox: Outbox | None = None) -> dict:
    ledger = ledger or InventoryLedger(db)
    accounting = accounting or AccountingEngine(db)
    outbox = outbox or Outbox(db)

    if not items:
        raise PurchaseError("purchase has no items")
    total = Decimal("0")
    for item in items:
        quantity = D(str(item["quantity"]).replace(",", ""))
        cost = D(str(item["unit_cost"]).replace(",", ""))
        if quantity <= 0:
            raise PurchaseError("purchase quantity must be positive")
        if cost < 0:
            raise PurchaseError("purchase cost cannot be negative")
        total += quantity * cost
    paid = D(str(paid_amount).replace(",", ""))
    if paid < 0 or paid > total:
        raise PurchaseError("paid amount must be between 0 and the total")
    credit_part = total - paid

    voucher_uuid = str(uuidlib.uuid4())
    with db.transaction() as tx:
        movement_uuids: list[str] = []
        for item in items:
            quantity = D(str(item["quantity"]).replace(",", ""))
            unit_cost = money(D(str(item["unit_cost"]).replace(",", "")))
            result = ledger.record_movement(
                tenant_id=tenant_id,
                branch_id=branch_id,
                product_uuid=item["product_uuid"],
                movement_type="PURCHASE_RECEIPT",
                direction=1,
                quantity=quantity,
                unit=item.get("unit") or "PIECE",
                cost=unit_cost,
                batch_no=item.get("batch_no"),
                expires_at=item.get("expires_at"),
                reference_type="PURCHASE",
                reference_uuid=voucher_uuid,
                created_by=created_by,
            )
            movement_uuids.append(result["uuid"])

        lines: list[tuple[str, Decimal, Decimal]] = [
            ("1200", total, Decimal("0"))
        ]
        if credit_part > 0:
            lines.append(("2000", Decimal("0"), credit_part))
        if paid > 0:
            lines.append(("1000", Decimal("0"), paid))
        journal = accounting.post_entry(
            tenant_id=tenant_id,
            lines=lines,
            memo=f"Purchase receipt {voucher_uuid[:8]}",
            source_type="PURCHASE",
            source_uuid=voucher_uuid,
        )

        tx.execute(
            "INSERT INTO purchase_vouchers (uuid, tenant_id, branch_id,"
            " device_id, supplier_uuid, total, paid_amount, journal_uuid,"
            " created_by) VALUES (?,?,?,?,?,?,?,?,?)",
            (voucher_uuid, tenant_id, branch_id, device_id, supplier_uuid,
             money(total), money(paid), journal["uuid"], created_by),
        )
        for item in items:
            quantity = D(str(item["quantity"]).replace(",", ""))
            line_total = quantity * D(
                str(item["unit_cost"]).replace(",", "")
            )
            tx.execute(
                "INSERT INTO purchase_items (voucher_uuid, product_uuid,"
                " quantity, unit_cost, line_total, batch_no, expires_at)"
                " VALUES (?,?,?,?,?,?,?)",
                (voucher_uuid, item["product_uuid"], str(quantity),
                 str(item["unit_cost"]), money(line_total),
                 item.get("batch_no"), item.get("expires_at")),
            )

        if paid > 0:
            tx.execute(
                "INSERT INTO payments (uuid, tenant_id, payment_type,"
                " reference_uuid, method, amount) VALUES (?,?,?,?,?,?)",
                (str(uuidlib.uuid4()), tenant_id, "SUPPLIER_PAYMENT",
                 voucher_uuid, "CASH" if payment_method == "CASH" else "OTHER",
                 money(paid)),
            )

        if credit_part > 0 and supplier_uuid:
            supplier = tx.query_one(
                "SELECT balance FROM suppliers WHERE uuid=? AND tenant_id=?",
                (supplier_uuid, tenant_id),
            )
            if supplier is None:
                raise PurchaseError("supplier does not belong to this tenant")
            tx.execute(
                "UPDATE suppliers SET balance=? WHERE uuid=? AND tenant_id=?",
                (money(D(supplier["balance"]) + credit_part), supplier_uuid,
                 tenant_id),
            )

        outbox.append(
            tenant_id=tenant_id,
            device_id=device_id,
            event_type="purchase.received",
            payload={
                "version": 1,
                "voucher_uuid": voucher_uuid,
                "supplier_uuid": supplier_uuid,
                "branch_id": branch_id,
                "total": money(total),
                "paid": money(paid),
                "credit": money(credit_part),
                "journal_entry_uuid": journal["uuid"],
                "items": [
                    {
                        "product_uuid": item["product_uuid"],
                        "quantity": money(D(str(item["quantity"]))),
                        "unit_cost": money(D(str(item["unit_cost"]))),
                    }
                    for item in items
                ],
            },
            references_sale=None,
        )

    return {
        "voucher_uuid": voucher_uuid,
        "total": money(total),
        "paid": money(paid),
        "credit_part": money(credit_part),
        "journal_entry": journal,
        "movement_uuids": movement_uuids,
    }
