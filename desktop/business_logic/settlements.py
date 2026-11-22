"""Customer and supplier payments (debt settlement).

Receiving a customer payment posts DR cash/bank, CR Accounts Receivable
1100, reduces the customer's balance, records a payments row and queues a
customer.payment outbox event. Paying a supplier is the mirror image
(DR 2000, CR cash) with a supplier.payment event.
"""

from __future__ import annotations

import uuid as uuidlib
from decimal import Decimal

from .accounting import AccountingEngine
from .money import D, money
from ..synchronization.outbox import Outbox


class SettlementError(ValueError):
    pass


def _payment_account(method: str) -> str:
    return "1000" if method == "CASH" else "1010"


def receive_customer_payment(db, *, tenant_id: str, device_id: str,
                             customer_uuid: str, amount,
                             method: str = "CASH",
                             received_by: str | None = None,
                             accounting: AccountingEngine | None = None,
                             outbox: Outbox | None = None) -> dict:
    accounting = accounting or AccountingEngine(db)
    outbox = outbox or Outbox(db)

    value = D(str(amount).replace(",", ""))
    if value <= 0:
        raise SettlementError("قيمة الدفعة يجب أن تكون أكبر من صفر")
    if method not in ("CASH", "CARD", "BANK", "WALLET"):
        raise SettlementError(f"طريقة دفع غير مدعومة: {method}")

    customer = db.query_one(
        "SELECT uuid, balance FROM customers WHERE uuid=? AND tenant_id=?",
        (customer_uuid, tenant_id),
    )
    if customer is None:
        raise SettlementError("العميل غير موجود في مؤسستك")

    payment_uuid = str(uuidlib.uuid4())
    with db.transaction() as tx:
        journal = accounting.post_entry(
            tenant_id=tenant_id,
            lines=[(_payment_account(method), value, Decimal("0")),
                   ("1100", Decimal("0"), value)],
            memo=f"Customer payment {customer_uuid[:8]}",
            source_type="PAYMENT",
            source_uuid=payment_uuid,
        )
        new_balance = max(D(customer["balance"]) - value, Decimal("0"))
        tx.execute(
            "UPDATE customers SET balance=? WHERE uuid=? AND tenant_id=?",
            (money(new_balance), customer_uuid, tenant_id),
        )
        tx.execute(
            "INSERT INTO payments (uuid, tenant_id, payment_type,"
            " reference_uuid, method, amount) VALUES (?,?,?,?,?,?)",
            (payment_uuid, tenant_id, "CUSTOMER_PAYMENT", customer_uuid,
             method if method != "WALLET" else "OTHER", money(value)),
        )
        outbox.append(
            tenant_id=tenant_id,
            device_id=device_id,
            event_type="customer.payment",
            payload={
                "version": 1,
                "payment_uuid": payment_uuid,
                "customer_uuid": customer_uuid,
                "amount": money(value),
                "method": method,
                "journal_entry_uuid": journal["uuid"],
            },
        )
    return {"payment_uuid": payment_uuid, "journal_entry": journal,
            "new_balance": money(new_balance)}


def pay_supplier(db, *, tenant_id: str, device_id: str,
                 supplier_uuid: str, amount, method: str = "CASH",
                 paid_by: str | None = None,
                 accounting: AccountingEngine | None = None,
                 outbox: Outbox | None = None) -> dict:
    accounting = accounting or AccountingEngine(db)
    outbox = outbox or Outbox(db)

    value = D(str(amount).replace(",", ""))
    if value <= 0:
        raise SettlementError("قيمة الدفعة يجب أن تكون أكبر من صفر")
    if method not in ("CASH", "CARD", "BANK", "WALLET"):
        raise SettlementError(f"طريقة دفع غير مدعومة: {method}")

    supplier = db.query_one(
        "SELECT uuid, balance FROM suppliers WHERE uuid=? AND tenant_id=?",
        (supplier_uuid, tenant_id),
    )
    if supplier is None:
        raise SettlementError("المورد غير موجود في مؤسستك")

    payment_uuid = str(uuidlib.uuid4())
    with db.transaction() as tx:
        journal = accounting.post_entry(
            tenant_id=tenant_id,
            lines=[("2000", value, Decimal("0")),
                   (_payment_account(method), Decimal("0"), value)],
            memo=f"Supplier payment {supplier_uuid[:8]}",
            source_type="PAYMENT",
            source_uuid=payment_uuid,
        )
        new_balance = max(D(supplier["balance"]) - value, Decimal("0"))
        tx.execute(
            "UPDATE suppliers SET balance=? WHERE uuid=? AND tenant_id=?",
            (money(new_balance), supplier_uuid, tenant_id),
        )
        tx.execute(
            "INSERT INTO payments (uuid, tenant_id, payment_type,"
            " reference_uuid, method, amount) VALUES (?,?,?,?,?,?)",
            (payment_uuid, tenant_id, "SUPPLIER_PAYMENT", supplier_uuid,
             method if method != "WALLET" else "OTHER", money(value)),
        )
        outbox.append(
            tenant_id=tenant_id,
            device_id=device_id,
            event_type="supplier.payment",
            payload={
                "version": 1,
                "payment_uuid": payment_uuid,
                "supplier_uuid": supplier_uuid,
                "amount": money(value),
                "method": method,
                "journal_entry_uuid": journal["uuid"],
            },
        )
    return {"payment_uuid": payment_uuid, "journal_entry": journal,
            "new_balance": money(new_balance)}
