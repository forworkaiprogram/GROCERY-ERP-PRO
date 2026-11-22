"""Stocktake (physical count submission).

Each counted line produces a COUNT ledger movement for the exact signed
delta (expected -> counted), plus an inventory.movement outbox event so
the cloud reconciles from the same append-only evidence.
"""

from __future__ import annotations

from decimal import Decimal

from .inventory import InventoryLedger
from .money import D, qty as qty_text
from ..synchronization.outbox import Outbox


class StocktakeError(ValueError):
    pass


def submit_count(db, ledger: InventoryLedger, outbox: Outbox, *,
                 tenant_id: str, branch_id: str, device_id: str,
                 counted_by: str | None, items: list[dict]) -> dict:
    if not items:
        raise StocktakeError("لا توجد بنود جرد")
    results: list[dict] = []
    with db.transaction() as tx:
        for item in items:
            product_uuid = item["product_uuid"]
            counted = D(str(item["counted"]).replace(",", ""))
            if counted < 0:
                raise StocktakeError("الكمية المجرودة لا يمكن أن تكون سالبة")
            balance = tx.query_one(
                "SELECT quantity FROM inventory_balances WHERE tenant_id=?"
                " AND branch_id=? AND product_uuid=?",
                (tenant_id, branch_id, product_uuid),
            )
            expected = D(balance["quantity"]) if balance else Decimal("0")
            delta = counted - expected
            out: dict = {
                "product_uuid": product_uuid,
                "expected": qty_text(expected),
                "counted": qty_text(counted),
                "delta": qty_text(delta),
            }
            if delta != 0:
                movement = ledger.record_movement(
                    tenant_id=tenant_id,
                    branch_id=branch_id,
                    product_uuid=product_uuid,
                    movement_type="COUNT",
                    direction=1 if delta > 0 else -1,
                    quantity=abs(delta),
                    unit="PIECE",
                    reference_type="STOCKTAKE",
                    created_by=counted_by,
                )
                outbox.append(
                    tenant_id=tenant_id,
                    device_id=device_id,
                    event_type="inventory.movement",
                    payload=ledger.movement_payload(movement["uuid"]),
                )
                out["applied"] = True
            else:
                out["applied"] = False
            results.append(out)
    return {"accepted": len(results), "adjusted": sum(
        1 for r in results if r["applied"]), "results": results}


def current_balances(db, tenant_id: str) -> list[dict]:
    return [
        {
            "product_uuid": r["product_uuid"],
            "name": r["name_ar"] or r["name"],
            "branch_id": r["branch_id"],
            "expected": qty_text(D(r["quantity"])),
        }
        for r in db.query_all(
            "SELECT b.product_uuid, b.quantity, b.branch_id, p.name,"
            " p.name_ar FROM inventory_balances b"
            " JOIN products p ON p.uuid = b.product_uuid"
            " WHERE b.tenant_id=? ORDER BY p.name",
            (tenant_id,),
        )
    ]
