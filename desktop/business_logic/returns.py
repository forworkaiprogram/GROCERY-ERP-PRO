"""Sales returns: full or partial, snapshot-priced, wallet-safe.

A return can never exceed the remaining un-returned quantity of each sale
line. The refund follows the ORIGINAL payment methods of the sale: cash
methods refund into the cash account, CREDIT reduces the customer's debt
(all balance math in Python Decimal). Inventory is restored with RETURN_IN
ledger movements and the balanced reversal entry is posted. No posted
entry is ever edited.
"""

from __future__ import annotations

import json
import uuid as uuidlib
from decimal import Decimal

from .accounting import AccountingEngine
from .inventory import InventoryLedger
from .money import D, money
from ..synchronization.outbox import Outbox

CASH_ACCOUNT_BY_METHOD = {
    "CASH": "1000", "CARD": "1010", "BANK": "1010", "WALLET": "1010",
}


class ReturnError(ValueError):
    pass


def _split_over_original_methods(db, sale_uuid: str, fallback_total: str):
    """Split method shares exactly (no rounding drift): all but the last
    share are quantized, the last absorbs the remainder."""
    rows = db.query_all(
        "SELECT method, amount FROM payments p"
        " WHERE p.payment_type='SALE' AND p.reference_uuid=?",
        (sale_uuid,),
    )
    if rows:
        by_method: dict[str, Decimal] = {}
        for r in rows:
            by_method[r["method"]] = (
                by_method.get(r["method"], Decimal("0")) + D(r["amount"])
            )
        shares = list(by_method.items())
    else:
        shares = [("CASH", D(fallback_total))]
    total_paid = sum((paid for _m, paid in shares), Decimal("0"))

    def split(refund_total: Decimal) -> list[tuple[str, Decimal]]:
        result: list[tuple[str, Decimal]] = []
        remaining = refund_total
        for index, (method, paid) in enumerate(shares):
            if index == len(shares) - 1:
                amount = remaining
            else:
                amount = (refund_total * paid / total_paid).quantize(
                    Decimal("0.01")
                )
                remaining -= amount
                remaining = max(remaining, Decimal("0"))
            if amount > 0:
                account = (
                    "1100" if method == "CREDIT"
                    else CASH_ACCOUNT_BY_METHOD.get(method, "1000")
                )
                result.append((account, amount))
        return result

    return split


def return_sale(db, *, tenant_id: str, branch_id: str, device_id: str,
                sale_uuid: str, items: list[dict], reason: str | None = None,
                approved_by: str | None = None,
                accounting: AccountingEngine | None = None,
                ledger: InventoryLedger | None = None,
                outbox: Outbox | None = None) -> dict:
    ledger = ledger or InventoryLedger(db)
    accounting = accounting or AccountingEngine(db)
    outbox = outbox or Outbox(db)

    sale = db.query_one("SELECT * FROM sales WHERE uuid=?", (sale_uuid,))
    if sale is None:
        raise ReturnError("الفاتورة غير موجودة")
    if sale["tenant_id"] != tenant_id:
        raise ReturnError("الفاتورة لا تنتمي لمؤسستك")
    if sale["status"] in ("VOID", "RETURNED"):
        raise ReturnError("لا يمكن مرتجع على فاتورة ملغاة أو مرتجعة بالكامل")
    if not items:
        raise ReturnError("حدد الصنف/الأصناف المراد إرجاعها")

    sale_items = db.query_all(
        "SELECT * FROM sale_items WHERE sale_uuid=?", (sale_uuid,)
    )
    items_by_id = {row["id"]: row for row in sale_items}

    refund_total = Decimal("0")
    prepared: list[dict] = []
    for item in items:
        sale_item_id = int(item["sale_item_id"])
        original = items_by_id.get(sale_item_id)
        if original is None:
            raise ReturnError("بند غير موجود في الفاتورة الأصلية")
        already_rows = db.query_all(
            "SELECT ri.quantity FROM return_items ri"
            " JOIN returns rt ON rt.uuid = ri.return_uuid"
            " WHERE rt.sale_uuid=? AND ri.sale_item_id=?",
            (sale_uuid, sale_item_id),
        )
        returned_qty = sum(
            (D(r["quantity"]) for r in already_rows), Decimal("0")
        )
        requested = D(str(item["quantity"]).replace(",", ""))
        original_qty = D(original["quantity"])
        if requested <= 0:
            raise ReturnError("كمية الإرجاع يجب أن تكون أكبر من صفر")
        if requested + returned_qty > original_qty:
            raise ReturnError(
                "كمية الإرجاع تتجاوز المتبقي للبند"
                f" (متبقي {original_qty - returned_qty})"
            )
        unit_price = D(original["unit_price"])
        line_refund = (unit_price * requested).quantize(Decimal("0.01"))
        refund_total += line_refund
        prepared.append({
            "sale_item_id": sale_item_id,
            "product_uuid": original["product_uuid"],
            "quantity": requested,
            "unit_price": unit_price,
            "line_total": line_refund,
        })

    if refund_total <= 0:
        raise ReturnError("إجمالي المرتجع صفر")

    split = _split_over_original_methods(db, sale_uuid, sale["total"])
    refund_lines = split(refund_total)
    credit_redeem = next(
        (amount for account, amount in refund_lines if account == "1100"),
        Decimal("0"),
    )
    return_uuid = str(uuidlib.uuid4())

    with db.transaction() as tx:
        movement_events: list[str] = []
        for p in prepared:
            movement = ledger.record_movement(
                tenant_id=tenant_id,
                branch_id=branch_id,
                product_uuid=p["product_uuid"],
                movement_type="RETURN_IN",
                direction=1,
                quantity=p["quantity"],
                unit="PIECE",
                reference_type="RETURN",
                reference_uuid=return_uuid,
                created_by=approved_by,
            )
            movement_events.append(movement["uuid"])

        journal = accounting.post_entry(
            tenant_id=tenant_id,
            lines=[("4010", refund_total, Decimal("0")),
                   *[(acc, Decimal("0"), amt) for acc, amt in refund_lines]],
            memo=f"Return of sale {sale['invoice_no']}",
            source_type="ADJUSTMENT",
            source_uuid=return_uuid,
        )

        if credit_redeem > 0 and sale["customer_uuid"]:
            customer = tx.query_one(
                "SELECT balance FROM customers WHERE uuid=? AND tenant_id=?",
                (sale["customer_uuid"], tenant_id),
            )
            if customer is not None:
                new_balance = max(D(customer["balance"]) - credit_redeem,
                                  Decimal("0"))
                tx.execute(
                    "UPDATE customers SET balance=? WHERE uuid=?"
                    " AND tenant_id=?",
                    (money(new_balance), sale["customer_uuid"], tenant_id),
                )

        tx.execute(
            "INSERT INTO returns (uuid, tenant_id, sale_uuid, branch_id,"
            " device_id, reason, total, approved_by, priced_snapshot)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (return_uuid, tenant_id, sale_uuid, branch_id, device_id, reason,
             money(refund_total), approved_by,
             json.dumps({
                 "refund_total": money(refund_total),
                 "items": [
                     {"sale_item_id": p["sale_item_id"],
                      "quantity": str(p["quantity"])}
                     for p in prepared
                 ],
             }, sort_keys=True)),
        )
        for p in prepared:
            tx.execute(
                "INSERT INTO return_items (return_uuid, sale_item_id,"
                " product_uuid, quantity, unit_price, line_total)"
                " VALUES (?,?,?,?,?,?)",
                (return_uuid, p["sale_item_id"], p["product_uuid"],
                 str(p["quantity"]), money(p["unit_price"]),
                 money(p["line_total"])),
            )
        tx.execute(
            "INSERT INTO payments (uuid, tenant_id, payment_type,"
            " reference_uuid, method, amount) VALUES (?,?,?,?,?,?)",
            (str(uuidlib.uuid4()), tenant_id, "REFUND", return_uuid,
             "OTHER", money(refund_total)),
        )

        outstanding = tx.query_one(
            "SELECT COUNT(1) AS n FROM sale_items si WHERE si.sale_uuid=?"
            " AND (SELECT COALESCE(SUM(ri.quantity), 0) FROM return_items ri"
            " JOIN returns rt ON rt.uuid = ri.return_uuid"
            " WHERE rt.sale_uuid = si.sale_uuid"
            " AND ri.sale_item_id = si.id) < si.quantity",
            (sale_uuid,),
        )
        if outstanding is not None and int(outstanding["n"]) == 0:
            tx.execute(
                "UPDATE sales SET status='RETURNED' WHERE uuid=?",
                (sale_uuid,),
            )
        else:
            tx.execute(
                "UPDATE sales SET status='PARTIALLY_RETURNED' WHERE uuid=?",
                (sale_uuid,),
            )

        outbox.append(
            tenant_id=tenant_id,
            device_id=device_id,
            event_type="inventory.movement",
            payload=ledger.movement_payload(movement_events[0]),
            references_sale=sale_uuid,
        )
        outbox.append(
            tenant_id=tenant_id,
            device_id=device_id,
            event_type="sale.returned",
            payload={
                "version": 1,
                "return_uuid": return_uuid,
                "sale_uuid": sale_uuid,
                "invoice_no": sale["invoice_no"],
                "reason": reason,
                "refund_total": money(refund_total),
                "items": [
                    {"sale_item_id": p["sale_item_id"],
                     "quantity": str(p["quantity"])}
                    for p in prepared
                ],
                "journal_entry_uuid": journal["uuid"],
            },
            references_sale=sale_uuid,
        )
    return {
        "return_uuid": return_uuid,
        "refund_total": money(refund_total),
        "journal_entry": journal,
    }
