"""Qt-free analytics over local data (Decimal-only money aggregation).

SQLite SUM()/arithmetic on TEXT columns silently coerces to FLOAT, which is
prohibited for monetary values, so every aggregation below sums in Python
with Decimal and returns Decimal instances (UI formats via money()).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from .money import D

TIER_BY_STATUS = {"ACTIVE": "ACTIVE"}


def dashboard_summary(db, tenant_id: str) -> dict:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    month_start = today[:8] + "01"

    def _sales(where: str, params: tuple) -> tuple[Decimal, Decimal, int]:
        rows = db.query_all(
            "SELECT total, cost_total FROM sales WHERE tenant_id=? AND " + where,
            (tenant_id, *params),
        )
        total = sum((D(r["total"]) for r in rows), Decimal("0"))
        cost = sum((D(r["cost_total"]) for r in rows), Decimal("0"))
        return total, cost, len(rows)

    today_total, today_cost, today_count = _sales(
        "date(created_at)=?", (today,)
    )
    month_total, month_cost, month_count = _sales(
        "date(created_at)>=? ", (month_start,)
    )
    life_total, life_cost, life_count = _sales("1=1", ())

    expenses = db.query_all(
        "SELECT amount FROM expense_vouchers WHERE tenant_id=?", (tenant_id,)
    )
    expenses_total = sum((D(r["amount"]) for r in expenses), Decimal("0"))

    balances = db.query_all(
        "SELECT b.quantity, p.cost FROM inventory_balances b"
        " JOIN products p ON p.uuid=b.product_uuid"
        " WHERE b.tenant_id=? AND p.status='ACTIVE'",
        (tenant_id,),
    )
    inventory_value = sum(
        (D(r["quantity"]) * D(r["cost"]) for r in balances), Decimal("0")
    )

    receivables = db.query_all(
        "SELECT balance FROM customers WHERE tenant_id=? AND balance > '0'",
        (tenant_id,),
    )
    receivables_total = sum((D(r["balance"]) for r in receivables), Decimal("0"))

    payables = db.query_all(
        "SELECT balance FROM suppliers WHERE tenant_id=? AND balance > '0'",
        (tenant_id,),
    )
    payables_total = sum((D(r["balance"]) for r in payables), Decimal("0"))

    products = db.query_all(
        "SELECT uuid, reorder_level FROM products WHERE tenant_id=? AND"
        " status='ACTIVE'",
        (tenant_id,),
    )
    balance_rows = db.query_all(
        "SELECT product_uuid, quantity, reserved_qty FROM inventory_balances"
        " WHERE tenant_id=?",
        (tenant_id,),
    )
    available: dict[str, Decimal] = {}
    for r in balance_rows:
        available[r["product_uuid"]] = available.get(
            r["product_uuid"], Decimal("0")
        ) + D(r["quantity"]) - D(r["reserved_qty"])
    low_stock_count = 0
    for p in products:
        reorder = D(p["reorder_level"])
        if reorder > 0 and available.get(p["uuid"], Decimal("0")) <= reorder:
            low_stock_count += 1

    pending_sales = db.query_one(
        "SELECT COUNT(*) AS n FROM sales WHERE tenant_id=? AND"
        " sync_state <> 'ACKNOWLEDGED'",
        (tenant_id,),
    )
    pending_events = db.query_one(
        "SELECT COUNT(*) AS n FROM outbox_events WHERE state IN ('PENDING','SENT')"
    )
    conflicts = db.query_one(
        "SELECT COUNT(*) AS n FROM outbox_events WHERE state IN ('CONFLICT','REJECTED')"
    )

    gross_profit = life_total - life_cost
    net_profit = gross_profit - expenses_total
    return {
        "today_sales_total": today_total,
        "today_sales_count": today_count,
        "month_sales_total": month_total,
        "month_sales_count": month_count,
        "lifetime_sales_total": life_total,
        "lifetime_sales_count": life_count,
        "gross_profit": gross_profit,
        "expenses_total": expenses_total,
        "net_profit": net_profit,
        "inventory_value": inventory_value,
        "receivables_total": receivables_total,
        "payables_total": payables_total,
        "low_stock_count": low_stock_count,
        "pending_sync_sales": int(pending_sales["n"]) if pending_sales else 0,
        "pending_sync_events": int(pending_events["n"]) if pending_events else 0,
        "sync_conflicts": int(conflicts["n"]) if conflicts else 0,
    }


def daily_sales(db, tenant_id: str, days: int = 30) -> list[dict]:
    """Daily sales totals (Decimal) for the last `days` days, newest first."""
    since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
    rows = db.query_all(
        "SELECT date(created_at) AS day, total, cost_total FROM sales"
        " WHERE tenant_id=? AND date(created_at)>=? ORDER BY day DESC",
        (tenant_id, since),
    )
    grouped: dict[str, dict] = {}
    for r in rows:
        slot = grouped.setdefault(
            r["day"],
            {"day": r["day"], "count": 0, "total": Decimal("0"), "cost": Decimal("0")},
        )
        slot["count"] += 1
        slot["total"] += D(r["total"])
        slot["cost"] += D(r["cost_total"])
    for slot in grouped.values():
        slot["profit"] = slot["total"] - slot["cost"]
    return sorted(grouped.values(), key=lambda s: s["day"], reverse=True)
