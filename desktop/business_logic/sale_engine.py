"""Local-first POS sale engine.

Implements the mandatory local-first sale workflow:

 1. Read local product/pricing data (caller's responsibility, via repos).
 2. Validate local permissions (caller passes an authorized context).
 3. Validate local inventory availability (offline allocations).
 4. Price the sale with Decimal.
 5. Generate sale id + per-device sale_no.
 6. Open ONE SQLite IMMEDIATE transaction.
 7. Persist sale + items, 8. payments, 9. inventory movements,
 10. provisional journal entry, 11. outbox events — atomically (12. commit).
13+. The caller reports success/printing; the SyncWorker drains the outbox.

If ANY step fails the transaction is rolled back completely: nothing is
written, no event is emitted, and the sale is NOT reported as saved.
Cloud acknowledgement is never part of this flow.
"""

from __future__ import annotations

import json
import uuid as uuidlib
from decimal import Decimal

from ..synchronization.outbox import Outbox
from .accounting import AccountingEngine
from .inventory import InventoryError, InventoryLedger
from .money import D, money
from .pricing import PricedLine, price_sale, price_line, sale_accounting_lines


class SaleValidationError(ValueError):
    pass


class InsufficientStockError(SaleValidationError):
    pass


class CreditLimitError(SaleValidationError):
    pass


class PaymentIncompleteError(SaleValidationError):
    pass


class SaleEngine:
    def __init__(self, db):
        self.db = db
        self.ledger = InventoryLedger(db)
        self.accounting = AccountingEngine(db)
        self.outbox = Outbox(db)

    def price_cart(
        self,
        *,
        tenant_id: str,
        items: list[dict],
        customer: dict | None = None,
    ) -> list[PricedLine]:
        """items: [{product_uuid, quantity, unit?, line_discount_bps?}]"""
        priced: list[PricedLine] = []
        for item in items:
            product = self.db.query_one(
                "SELECT * FROM products WHERE tenant_id=? AND uuid=? AND status='ACTIVE'",
                (tenant_id, item["product_uuid"]),
            )
            if product is None:
                raise SaleValidationError(
                    f"product not available locally: {item['product_uuid']}"
                )
            product = dict(product)
            priced.append(
                price_line(
                    product=product,
                    quantity=item["quantity"],
                    unit=item.get("unit") or product.get("default_unit") or "PIECE",
                    customer=customer,
                    line_discount_bps=item.get("line_discount_bps"),
                )
            )
        return priced

    def validate_stock(
        self,
        *,
        tenant_id: str,
        branch_id: str,
        device_id: str,
        priced: list[PricedLine],
    ) -> None:
        needed: dict[str, Decimal] = {}
        for line in priced:
            needed[line.product_uuid] = needed.get(line.product_uuid, Decimal("0")) + line.quantity
        for product_uuid, quantity in needed.items():
            available = self.ledger.available_qty(
                tenant_id, branch_id, product_uuid, device_id
            )
            if quantity > available:
                raise InsufficientStockError(
                    f"insufficient offline stock for {product_uuid}:"
                    f" requested {quantity}, available {available}"
                )

    def commit_sale(
        self,
        *,
        tenant_id: str,
        branch_id: str,
        device_id: str,
        cashier_id: str,
        items: list[dict],
        payments: list[dict],
        customer: dict | None = None,
    ) -> dict:
        """Execute and commit the sale locally. Returns the committed record.

        payments: [{method, amount, meta?}] — amounts sum must match total
        unless a CREDIT payment is present, which is validated against the
        customer credit limit.
        """
        priced = self.price_cart(
            tenant_id=tenant_id, items=items, customer=customer
        )
        priced_sale = price_sale(priced)
        total = priced_sale.total
        paid = sum((D(p["amount"]) for p in payments), Decimal("0"))
        credit_lines = [p for p in payments if p["method"] == "CREDIT"]
        credit_amount = sum((D(p["amount"]) for p in credit_lines), Decimal("0"))
        if paid != total:
            raise PaymentIncompleteError(
                f"payments {paid} do not equal sale total {total}"
            )
        if credit_amount > 0:
            if customer is None:
                raise CreditLimitError("credit sale requires a customer")
            limit = D(customer.get("credit_limit", "0"))
            current_balance = D(customer.get("balance", "0"))
            if current_balance + credit_amount > limit:
                raise CreditLimitError(
                    f"credit limit exceeded: balance {current_balance}"
                    f" + {credit_amount} > limit {limit}"
                )

        sale_uuid = str(uuidlib.uuid4())
        sale_no = self._next_sale_no(device_id)
        invoice_no = f"INV-{device_id[:8].upper()}-{sale_no:07d}"

        with self.db.transaction() as db:
            self.validate_stock(
                tenant_id=tenant_id,
                branch_id=branch_id,
                device_id=device_id,
                priced=priced,
            )
            db.execute(
                "INSERT INTO sales (uuid, tenant_id, branch_id, device_id, cashier_id,"
                " invoice_no, sale_no, customer_uuid, subtotal, discount_total,"
                " tax_total, total, cost_total, priced_snapshot)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    sale_uuid,
                    tenant_id,
                    branch_id,
                    device_id,
                    cashier_id,
                    invoice_no,
                    sale_no,
                    customer["uuid"] if customer else None,
                    money(priced_sale.subtotal),
                    money(priced_sale.discount_total),
                    money(priced_sale.tax_total),
                    money(total),
                    money(priced_sale.cost_total),
                    priced_sale.as_snapshot(),
                ),
            )
            for line in priced:
                db.execute(
                    "INSERT INTO sale_items (sale_uuid, product_uuid, unit, quantity,"
                    " unit_price, discount, tax_rate_bps, tax_amount, line_total,"
                    " unit_cost) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (
                        sale_uuid,
                        line.product_uuid,
                        line.unit,
                        str(line.quantity),
                        str(line.unit_price),
                        str(line.discount),
                        line.tax_rate_bps,
                        str(line.tax_amount),
                        str(line.line_total),
                        str(line.unit_cost),
                    ),
                )
            for p in payments:
                db.execute(
                    "INSERT INTO payments (tenant_id, uuid, payment_type,"
                    " reference_uuid, method, amount, meta) VALUES (?,?,?,?,?,?,?)",
                    (
                        tenant_id,
                        str(uuidlib.uuid4()),
                        "SALE",
                        sale_uuid,
                        p["method"],
                        money(p["amount"]),
                        json.dumps(p.get("meta", {}), sort_keys=True),
                    ),
                )
            movement_uuids = []
            for line in priced:
                result = self.ledger.record_movement(
                    tenant_id=tenant_id,
                    branch_id=branch_id,
                    product_uuid=line.product_uuid,
                    movement_type="SALE",
                    direction=-1,
                    quantity=line.quantity,
                    unit=line.unit,
                    reference_type="SALE",
                    reference_uuid=sale_uuid,
                    created_by=cashier_id,
                )
                movement_uuids.append(result["uuid"])
            journal = self.accounting.post_entry(
                tenant_id=tenant_id,
                lines=sale_accounting_lines(priced_sale),
                memo=f"Sale {invoice_no}",
                source_type="SALE",
                source_uuid=sale_uuid,
            )
            if customer and credit_amount > 0:
                self.customers_add_balance(db, tenant_id, customer["uuid"], credit_amount)
            self.outbox.append(
                tenant_id=tenant_id,
                device_id=device_id,
                event_type="sale.created",
                payload={
                    "version": 1,
                    "sale_uuid": sale_uuid,
                    "invoice_no": invoice_no,
                    "branch_id": branch_id,
                    "cashier_id": cashier_id,
                    "customer_uuid": customer["uuid"] if customer else None,
                    "totals": {
                        "subtotal": money(priced_sale.subtotal),
                        "discount": money(priced_sale.discount_total),
                        "tax": money(priced_sale.tax_total),
                        "total": money(total),
                        "cost": money(priced_sale.cost_total),
                    },
                    "items": [line.as_dict() for line in priced],
                    "payments": [
                        {"method": p["method"], "amount": money(p["amount"])}
                        for p in payments
                    ],
                    "journal_entry_uuid": journal["uuid"],
                },
                references_sale=sale_uuid,
            )
            for mid in movement_uuids:
                self.outbox.append(
                    tenant_id=tenant_id,
                    device_id=device_id,
                    event_type="inventory.movement",
                    payload=self.ledger.movement_payload(mid),
                    references_sale=sale_uuid,
                )
            self.outbox.append(
                tenant_id=tenant_id,
                device_id=device_id,
                event_type="accounting.journal_posted",
                payload=self.accounting.entry_payload(journal["uuid"]),
                references_sale=sale_uuid,
            )

        return {
            "sale_uuid": sale_uuid,
            "invoice_no": invoice_no,
            "sale_no": sale_no,
            "total": money(total),
            "snapshot": priced_sale.as_snapshot(),
            "journal_entry": journal,
        }

    @staticmethod
    def customers_add_balance(db, tenant_id: str, customer_uuid: str, delta: Decimal) -> None:
        row = db.query_one(
            "SELECT balance FROM customers WHERE tenant_id=? AND uuid=?",
            (tenant_id, customer_uuid),
        )
        if row is None:
            raise SaleValidationError("customer not found")
        db.execute(
            "UPDATE customers SET balance=? WHERE tenant_id=? AND uuid=?",
            (money(D(row["balance"]) + delta), tenant_id, customer_uuid),
        )

    def get_sale(self, sale_uuid: str) -> dict:
        sale = dict(self.db.query_one("SELECT * FROM sales WHERE uuid=?", (sale_uuid,)))
        sale["items"] = [
            dict(r)
            for r in self.db.query_all(
                "SELECT * FROM sale_items WHERE sale_uuid=? ORDER BY id", (sale_uuid,)
            )
        ]
        sale["payments"] = [
            dict(r)
            for r in self.db.query_all(
                "SELECT * FROM payments WHERE payment_type='SALE' AND reference_uuid=?"
                " ORDER BY id",
                (sale_uuid,),
            )
        ]
        return sale

    def _next_sale_no(self, device_id: str) -> int:
        row = self.db.query_one(
            "SELECT COALESCE(MAX(sale_no), 0) AS n FROM sales WHERE device_id=?",
            (device_id,),
        )
        return int(row["n"]) + 1
