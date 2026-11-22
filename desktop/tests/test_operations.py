"""Tests for the business-operation engines added with the ERP rebuild:
purchases, returns, cash sessions, debt settlements, stocktake, local auth.
All Qt-free; money/quantity math is Decimal-only (no SQLite SUM on TEXT).
"""

from decimal import Decimal

from desktop.business_logic.money import D

import pytest

from desktop.business_logic.cash_sessions import CashSessionService
from desktop.business_logic.expenses import record_expense
from desktop.business_logic.purchases import PurchaseError, receive_purchase
from desktop.business_logic.returns import ReturnError, return_sale
from desktop.business_logic.settlements import (
    SettlementError,
    pay_supplier,
    receive_customer_payment,
)
from desktop.business_logic.stocktake import submit_count
from desktop.security.local_auth import LocalAuth, LocalAuthError

TENANT = "11111111-1111-1111-1111-111111111111"
MILK = "aaaa1111-0000-0000-0000-000000000002"
CUST = "bbbb1111-0000-0000-0000-000000000003"
SUPP = "cccc1111-0000-0000-0000-000000000004"


@pytest.fixture()
def seeded(runtime):
    runtime.db.execute(
        "UPDATE device_identity SET tenant_id=?, branch_id=?,"
        " registration_status='ACTIVE' WHERE id=1",
        (TENANT, "branch-1"),
    )
    runtime.db.execute(
        "INSERT INTO customers (uuid, tenant_id, name, phone, balance)"
        " VALUES (?,?,?,?, '0')", (CUST, TENANT, "عميل تجريبي", "77777"),
    )
    runtime.db.execute(
        "INSERT INTO suppliers (uuid, tenant_id, name, balance)"
        " VALUES (?,?,?, '0')", (SUPP, TENANT, "مورد تجريبي"),
    )
    runtime.db.execute(
        "INSERT INTO products (uuid, tenant_id, sku, name, cost, price,"
        " default_unit) VALUES (?,?,?,?,?, '1000', 'PIECE')",
        (MILK, TENANT, "MILK-1", "Milk 1L", "500"),
    )
    return runtime


def _grant_stock(runtime, quantity=10):
    with runtime.db.transaction():
        runtime.inventory.record_movement(
            tenant_id=TENANT, branch_id="branch-1", product_uuid=MILK,
            movement_type="PURCHASE_RECEIPT", direction=1, quantity=quantity,
            unit="PIECE", reference_type="PURCHASE",
        )


def _sell(runtime, quantity=3, method="CASH"):
    return runtime.sales.commit_sale(
        tenant_id=TENANT, branch_id="branch-1",
        device_id=runtime.device["device_id"], cashier_id="c1",
        customer=({'uuid': CUST, 'credit_limit': '10000', 'balance': '0', 'discount_bps': 0} if method != "CASH" else None),
        items=[{"product_uuid": MILK, "quantity": quantity, "unit": "PIECE"}],
        payments=[{"method": method, "amount": str(int(quantity) * 1000)}],
    )


def _journal_totals(runtime, entry_uuid):
    rows = runtime.db.query_all(
        "SELECT debit, credit FROM journal_lines WHERE entry_uuid=?",
        (entry_uuid,),
    )
    debits = sum((Decimal(r["debit"]) for r in rows), Decimal("0"))
    credits = sum((Decimal(r["credit"]) for r in rows), Decimal("0"))
    return debits, credits


def test_purchase_receipt_full_flow(seeded):
    runtime = seeded
    receive_purchase(
        runtime.db,
        tenant_id=TENANT, branch_id="branch-1",
        device_id=runtime.device["device_id"], supplier_uuid=SUPP,
        items=[{"product_uuid": MILK, "quantity": "24", "unit_cost": "500"}],
        paid_amount="12000", created_by="admin",
    )
    balance = runtime.db.query_one(
        "SELECT quantity FROM inventory_balances WHERE product_uuid=?",
        (MILK,),
    )
    assert float(balance["quantity"]) == 24.0
    supplier = runtime.db.query_one(
        "SELECT balance FROM suppliers WHERE uuid=?", (SUPP,)
    )
    assert D(supplier["balance"]) == 0
    events = [e["event_type"] for e in runtime.db.query_all(
        "SELECT event_type FROM outbox_events"
    )]
    assert events.count("purchase.received") == 1


def test_purchase_journal_balanced(seeded):
    runtime = seeded
    result = receive_purchase(
        runtime.db,
        tenant_id=TENANT, branch_id="branch-1",
        device_id=runtime.device["device_id"], supplier_uuid=SUPP,
        items=[{"product_uuid": MILK, "quantity": "24", "unit_cost": "500"}],
        paid_amount="6000", created_by="admin",
    )
    debits, credits = _journal_totals(
        runtime, result["journal_entry"]["uuid"]
    )
    assert debits == credits == Decimal("12000.00")


def test_purchase_partial_credit_updates_supplier_balance(seeded):
    runtime = seeded
    receive_purchase(
        runtime.db,
        tenant_id=TENANT, branch_id="branch-1",
        device_id=runtime.device["device_id"], supplier_uuid=SUPP,
        items=[{"product_uuid": MILK, "quantity": "10", "unit_cost": "500"}],
        paid_amount="2000", created_by="admin",
    )
    supplier = runtime.db.query_one(
        "SELECT balance FROM suppliers WHERE uuid=?", (SUPP,)
    )
    assert supplier["balance"] == "3000.00"


def test_purchase_rejects_bad_input(seeded):
    runtime = seeded
    with pytest.raises(PurchaseError):
        receive_purchase(
            runtime.db, tenant_id=TENANT, branch_id="b", device_id="d",
            supplier_uuid=None, items=[], paid_amount=0,
        )
    with pytest.raises(PurchaseError):
        receive_purchase(
            runtime.db, tenant_id=TENANT, branch_id="b", device_id="d",
            supplier_uuid=None,
            items=[{"product_uuid": MILK, "quantity": "1",
                    "unit_cost": "100"}],
            paid_amount="999",
        )


def test_return_full_flow(seeded):
    runtime = seeded
    _grant_stock(runtime, 10)
    sale = _sell(runtime, quantity=3)
    sale_row = runtime.db.query_one(
        "SELECT id FROM sale_items WHERE sale_uuid=?", (sale["sale_uuid"],)
    )
    result = return_sale(
        runtime.db,
        tenant_id=TENANT, branch_id="branch-1",
        device_id=runtime.device["device_id"], sale_uuid=sale["sale_uuid"],
        items=[{"sale_item_id": sale_row["id"], "quantity": "2"}],
        reason="تالف", approved_by="admin",
    )
    assert result["refund_total"] == "2000.00"
    debits, credits = _journal_totals(
        runtime, result["journal_entry"]["uuid"]
    )
    assert debits == credits == Decimal("2000.00")
    balance = runtime.db.query_one(
        "SELECT quantity FROM inventory_balances WHERE product_uuid=?",
        (MILK,),
    )
    assert float(balance["quantity"]) == 9.0  # 10 - 3 + 2
    events = [e["event_type"] for e in runtime.db.query_all(
        "SELECT event_type FROM outbox_events"
    )]
    assert events.count("sale.returned") == 1
    sale_status = runtime.db.query_one(
        "SELECT status FROM sales WHERE uuid=?", (sale["sale_uuid"],)
    )["status"]
    assert sale_status == "PARTIALLY_RETURNED"


def test_return_cannot_exceed_sold_quantity(seeded):
    runtime = seeded
    _grant_stock(runtime, 10)
    sale = _sell(runtime, quantity=3)
    sale_item = runtime.db.query_one(
        "SELECT id FROM sale_items WHERE sale_uuid=?", (sale["sale_uuid"],)
    )
    with pytest.raises(ReturnError):
        return_sale(
            runtime.db, tenant_id=TENANT, branch_id="branch-1",
            device_id=runtime.device["device_id"],
            sale_uuid=sale["sale_uuid"],
            items=[{"sale_item_id": sale_item["id"], "quantity": "4"}],
            approved_by="admin",
        )


def test_return_credit_sale_reduces_customer_debt(seeded):
    runtime = seeded
    _grant_stock(runtime, 10)
    sale = _sell(runtime, quantity=3, method="CREDIT")
    customer = runtime.db.query_one(
        "SELECT balance FROM customers WHERE uuid=?", (CUST,)
    )
    assert customer["balance"] == "3000.00"
    sale_item = runtime.db.query_one(
        "SELECT id FROM sale_items WHERE sale_uuid=?", (sale["sale_uuid"],)
    )
    return_sale(
        runtime.db, tenant_id=TENANT, branch_id="branch-1",
        device_id=runtime.device["device_id"], sale_uuid=sale["sale_uuid"],
        items=[{"sale_item_id": sale_item["id"], "quantity": "1"}],
        approved_by="admin",
    )
    customer = runtime.db.query_one(
        "SELECT balance FROM customers WHERE uuid=?", (CUST,)
    )
    assert customer["balance"] == "2000.00"


def test_cash_session_expected_and_discrepancy(seeded):
    runtime = seeded
    _grant_stock(runtime, 10)
    service = CashSessionService(runtime.db, runtime.outbox)
    session = service.open_session(
        tenant_id=TENANT, branch_id="branch-1",
        device_id=runtime.device["device_id"], cashier_id="c1",
        opening_balance="1000",
    )
    _sell(runtime, quantity=3)  # 3000 CASH in
    record_expense(
        runtime.db, runtime.accounting, runtime.outbox,
        tenant_id=TENANT, device_id=runtime.device["device_id"],
        category="إيجار", amount="500", paid_from_account="1000",
        expense_account="6100", payment_method="CASH",
    )
    open_session = service.current_open(runtime.device["device_id"])
    summary = service.cash_summary(open_session)
    assert summary["cash_in"] == Decimal("3000.00")
    assert summary["cash_out"] == Decimal("500.00")
    assert summary["expected"] == Decimal("3500.00")
    closed = service.close_session(
        session_uuid=session["uuid"], closing_balance="3500"
    )
    assert closed["discrepancy"] == "0.00"
    events = [e["event_type"] for e in runtime.db.query_all(
        "SELECT event_type FROM outbox_events"
    )]
    assert events.count("cash.session_closed") == 1


def test_customer_and_supplier_settlement(seeded):
    runtime = seeded
    _grant_stock(runtime, 10)
    _sell(runtime, quantity=3, method="CREDIT")  # customer owes 3000
    result = receive_customer_payment(
        runtime.db, tenant_id=TENANT, device_id=runtime.device["device_id"],
        customer_uuid=CUST, amount="1000", method="CASH",
    )
    customer = runtime.db.query_one(
        "SELECT balance FROM customers WHERE uuid=?", (CUST,)
    )
    assert customer["balance"] == "2000.00"
    debits, credits = _journal_totals(
        runtime, result["journal_entry"]["uuid"]
    )
    assert debits == credits == Decimal("1000.00")

    receive_purchase(
        runtime.db, tenant_id=TENANT, branch_id="branch-1",
        device_id=runtime.device["device_id"], supplier_uuid=SUPP,
        items=[{"product_uuid": MILK, "quantity": "2", "unit_cost": "500"}],
        paid_amount="0", created_by="admin",
    )
    supplier = runtime.db.query_one(
        "SELECT balance FROM suppliers WHERE uuid=?", (SUPP,)
    )
    assert supplier["balance"] == "1000.00"
    pay_supplier(
        runtime.db, tenant_id=TENANT, device_id=runtime.device["device_id"],
        supplier_uuid=SUPP, amount="400", method="CASH",
    )
    supplier = runtime.db.query_one(
        "SELECT balance FROM suppliers WHERE uuid=?", (SUPP,)
    )
    assert supplier["balance"] == "600.00"


def test_settlement_rejects_negative_amount(seeded):
    runtime = seeded
    with pytest.raises(SettlementError):
        receive_customer_payment(
            runtime.db, tenant_id=TENANT, device_id="d", customer_uuid=CUST,
            amount="-5",
        )


def test_stocktake_applies_signed_deltas(seeded):
    runtime = seeded
    _grant_stock(runtime, 10)
    result = submit_count(
        runtime.db, runtime.inventory, runtime.outbox,
        tenant_id=TENANT, branch_id="branch-1",
        device_id=runtime.device["device_id"], counted_by="admin",
        items=[{"product_uuid": MILK, "counted": "8"}],
    )
    assert result["adjusted"] == 1
    balance = runtime.db.query_one(
        "SELECT quantity FROM inventory_balances WHERE product_uuid=?",
        (MILK,),
    )
    assert float(balance["quantity"]) == 8.0
    events = [e["event_type"] for e in runtime.db.query_all(
        "SELECT event_type FROM outbox_events"
    )]
    assert events.count("inventory.movement") == 1


def test_local_auth_flow(seeded):
    runtime = seeded
    auth = LocalAuth(runtime.db)
    first = auth.ensure_default_admin() or {"role": "admin"}
    assert first["role"] == "admin"
    assert auth.ensure_default_admin() is None  # idempotent

    session = auth.login("admin", "admin123")
    assert session["role"] == "admin"
    with pytest.raises(LocalAuthError):
        auth.login("admin", "wrong")

    user = auth.create_user(
        username="cashier1", name="محمد", role="cashier",
        password="secret1",
    )
    assert auth.login("cashier1", "secret1")["role"] == "cashier"
    auth.set_status(user["uuid"], "DISABLED")
    with pytest.raises(LocalAuthError):
        auth.login("cashier1", "secret1")
    auth.set_password("cashier1", "newpass1")
    with pytest.raises(LocalAuthError):
        auth.login("cashier1", "newpass1")  # disabled stays disabled
    auth.set_status(user["uuid"], "ACTIVE")
    assert auth.login("cashier1", "newpass1")["role"] == "cashier"
