"""Expense vouchers with double-entry posting (local, provisional until
centrally posted). The voucher row and its balanced journal entry are
committed in ONE transaction, then an outbox event is appended so the
cloud may mirror it when connectivity returns.
"""

from __future__ import annotations

import uuid as uuidlib
from decimal import Decimal

from .money import D, money

PAYMENT_METHODS = frozenset({"CASH", "CARD", "BANK", "WALLET"})


class ExpenseError(ValueError):
    pass


def record_expense(
    db,
    accounting,
    outbox,
    *,
    tenant_id: str,
    device_id: str,
    category: str,
    amount,
    paid_from_account: str,
    expense_account: str,
    paid_to: str | None = None,
    payment_method: str = "CASH",
    approved_by: str | None = None,
) -> dict:
    amount = D(str(amount).replace(",", ""))
    if amount <= 0:
        raise ExpenseError("expense amount must be positive")
    if payment_method not in PAYMENT_METHODS:
        raise ExpenseError(f"invalid payment method {payment_method!r}")
    if not category:
        raise ExpenseError("expense category is required")
    if paid_from_account == expense_account:
        raise ExpenseError("pay-from and expense accounts must differ")

    voucher_uuid = str(uuidlib.uuid4())
    with db.transaction() as tx:
        journal = accounting.post_entry(
            tenant_id=tenant_id,
            lines=[
                (expense_account, amount, Decimal("0")),
                (paid_from_account, Decimal("0"), amount),
            ],
            memo=f"Expense {category}",
            source_type="EXPENSE",
            source_uuid=voucher_uuid,
        )
        tx.execute(
            "INSERT INTO expense_vouchers (uuid, tenant_id, category, amount,"
            " paid_from_account, paid_to, payment_method, approved_by, journal_uuid)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (
                voucher_uuid, tenant_id, category, money(amount),
                paid_from_account, paid_to, payment_method, approved_by,
                journal["uuid"],
            ),
        )
        outbox.append(
            tenant_id=tenant_id,
            device_id=device_id,
            event_type="expense.created",
            payload={
                "version": 1,
                "voucher_uuid": voucher_uuid,
                "category": category,
                "amount": money(amount),
                "payment_method": payment_method,
                "paid_from_account": paid_from_account,
                "expense_account": expense_account,
                "journal_entry_uuid": journal["uuid"],
            },
        )
    return {"voucher_uuid": voucher_uuid, "journal_entry": journal}
