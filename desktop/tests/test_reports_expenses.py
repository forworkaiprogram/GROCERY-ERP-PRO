"""Tests for the dashboard/reports analytics and expense vouchers (Qt-free)."""

from decimal import Decimal

import pytest

from desktop.business_logic.expenses import ExpenseError, record_expense
from desktop.business_logic.reports import daily_sales, dashboard_summary

TENANT = "11111111-1111-1111-1111-111111111111"
MILK = "aaaa1111-0000-0000-0000-000000000001"


def _seed_product_with_stock(runtime, qty=100):
    runtime.db.execute(
        "UPDATE device_identity SET tenant_id=?, branch_id=?,"
        " registration_status='ACTIVE' WHERE id=1",
        (TENANT, "branch-1"),
    )
    runtime.db.execute(
        "INSERT INTO products (uuid, tenant_id, sku, name, cost, price,"
        " default_unit) VALUES (?,?,?,?,?,?, 'PIECE')",
        (MILK, TENANT, "MILK-1", "Milk 1L", "500", "1000"),
    )
    with runtime.db.transaction() as db:
        runtime.inventory.record_movement(
            tenant_id=TENANT,
            branch_id="branch-1",
            product_uuid=MILK,
            movement_type="PURCHASE_RECEIPT",
            direction=1,
            quantity=qty,
            unit="PIECE",
            reference_type="PURCHASE",
        )


def _sell(runtime, quantity):
    return runtime.sales.commit_sale(
        tenant_id=TENANT,
        branch_id="branch-1",
        device_id=runtime.device["device_id"],
        cashier_id="c1",
        items=[{"product_uuid": MILK, "quantity": quantity, "unit": "PIECE"}],
        payments=[{"method": "CASH", "amount": str(int(quantity) * 1000)}],
    )


def test_dashboard_summary_after_sale_and_expense(runtime):
    _seed_product_with_stock(runtime)
    _sell(runtime, 5)
    summary = dashboard_summary(runtime.db, TENANT)
    assert summary["today_sales_total"] == Decimal("5000.00")
    assert summary["today_sales_count"] == 1
    assert summary["inventory_value"] == Decimal("47500.00")  # 95 * 500
    assert summary["gross_profit"] == Decimal("2500.00")  # 5000 - 5*500
    assert summary["net_profit"] == summary["gross_profit"]  # no expenses yet
    today = summary["today_sales_total"]
    assert dashboard_summary(runtime.db, "other-tenant")["today_sales_total"] == Decimal("0")


def test_expense_voucher_posts_balanced_journal_and_outbox(runtime):
    _seed_product_with_stock(runtime)
    before = len(runtime.db.query_all(
        "SELECT id FROM outbox_events WHERE event_type='expense.created'"
    ))
    with runtime.db.transaction() as db:
        pass
    result = record_expense(
        runtime.db,
        runtime.accounting,
        runtime.outbox,
        tenant_id=TENANT,
        device_id=runtime.device["device_id"],
        category="RI-JE",
        amount="10,000",  # thousands separator must be accepted
        paid_from_account="1000",
        expense_account="6100",
        payment_method="CASH",
    )
    voucher = runtime.db.query_one(
        "SELECT * FROM expense_vouchers WHERE uuid=?",
        (result["voucher_uuid"],),
    )
    assert voucher is not None
    assert voucher["amount"] == "10000.00"
    assert voucher["journal_uuid"] == result["journal_entry"]["uuid"]

    lines = runtime.db.query_all(
        "SELECT debit, credit FROM journal_lines WHERE entry_uuid=?",
        (result["journal_entry"]["uuid"],),
    )
    debits = sum((Decimal(r["debit"]) for r in lines), Decimal("0"))
    credits = sum((Decimal(r["credit"]) for r in lines), Decimal("0"))
    assert debits == credits == Decimal("10000.00")

    summary = dashboard_summary(runtime.db, TENANT)
    assert summary["expenses_total"] == Decimal("10000.00")
    assert summary["net_profit"] == summary["gross_profit"] - Decimal("10000.00")

    after = len(runtime.db.query_all(
        "SELECT id FROM outbox_events WHERE event_type='expense.created'"
    ))
    assert after == before + 1


def test_expense_rejects_invalid_input(runtime):
    _seed_product_with_stock(runtime)
    with pytest.raises(ExpenseError):
        record_expense(
            runtime.db, runtime.accounting, runtime.outbox,
            tenant_id=TENANT, device_id=runtime.device["device_id"],
            category="X", amount="-5",
            paid_from_account="1000", expense_account="6100",
        )
    with pytest.raises(ExpenseError):
        record_expense(
            runtime.db, runtime.accounting, runtime.outbox,
            tenant_id=TENANT, device_id=runtime.device["device_id"],
            category="X", amount="5", payment_method="BITCOIN",
            paid_from_account="1000", expense_account="6100",
        )
    with pytest.raises(ExpenseError):
        record_expense(
            runtime.db, runtime.accounting, runtime.outbox,
            tenant_id=TENANT, device_id=runtime.device["device_id"],
            category="X", amount="5",
            paid_from_account="6100", expense_account="6100",
        )


def test_daily_sales_report(runtime):
    _seed_product_with_stock(runtime)
    _sell(runtime, 2)
    rows = daily_sales(runtime.db, TENANT)
    assert len(rows) == 1
    assert rows[0]["count"] == 1
    assert rows[0]["total"] == Decimal("2000.00")
    assert rows[0]["profit"] == Decimal("1000.00")
