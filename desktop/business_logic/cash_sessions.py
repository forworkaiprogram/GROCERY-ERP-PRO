"""Cash register sessions (shifts).

A session is opened per device; on close the expected cash balance is
computed from real recorded cash flows since opening (customer cash
receipts in, expense vouchers out) -- Decimal only. The discrepancy is
stored, never hidden.
"""

from __future__ import annotations

import uuid as uuidlib
from datetime import datetime, timezone
from decimal import Decimal

from .money import D, money
from ..synchronization.outbox import Outbox


class SessionError(ValueError):
    pass


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


class CashSessionService:
    def __init__(self, db, outbox: Outbox | None = None):
        self.db = db
        self.outbox = outbox or Outbox(db)

    def open_session(self, *, tenant_id: str, branch_id: str,
                     device_id: str, cashier_id: str,
                     opening_balance) -> dict:
        existing = self.current_open(device_id)
        if existing:
            raise SessionError("يوجد وردية مفتوحة لهذا الجهاز — أغلقها أولًا")
        opening = D(str(opening_balance).replace(",", ""))
        if opening < 0:
            raise SessionError("الرصيد الافتتاحي لا يمكن أن يكون سالبًا")
        session_uuid = str(uuidlib.uuid4())
        self.db.execute(
            "INSERT INTO cash_sessions (uuid, tenant_id, branch_id,"
            " device_id, cashier_id, opening_balance)"
            " VALUES (?,?,?,?,?,?)",
            (session_uuid, tenant_id, branch_id, device_id, cashier_id,
             money(opening)),
        )
        return {"uuid": session_uuid, "opening_balance": money(opening)}

    def current_open(self, device_id: str) -> dict | None:
        row = self.db.query_one(
            "SELECT * FROM cash_sessions WHERE device_id=?"
            " AND status='OPEN' ORDER BY opened_at DESC LIMIT 1",
            (device_id,),
        )
        return dict(row) if row else None

    def cash_summary(self, session: dict) -> dict:
        cash_in_rows = self.db.query_all(
            "SELECT p.amount FROM sales s"
            " JOIN payments p ON p.payment_type='SALE'"
            " AND p.reference_uuid = s.uuid AND p.method='CASH'"
            " WHERE s.device_id=? AND s.created_at >= ? AND s.tenant_id=?",
            (session["device_id"], session["opened_at"], session["tenant_id"]),
        )
        expense_rows = self.db.query_all(
            "SELECT amount FROM expense_vouchers"
            " WHERE payment_method='CASH' AND voucher_date >= ?"
            " AND tenant_id=?",
            (session["opened_at"][:10], session["tenant_id"]),
        )
        total_in = sum((D(r["amount"]) for r in cash_in_rows), Decimal("0"))
        total_out = sum((D(r["amount"]) for r in expense_rows), Decimal("0"))
        opening = D(session["opening_balance"])
        expected = opening + total_in - total_out
        return {
            "opening": opening,
            "cash_in": total_in,
            "cash_out": total_out,
            "expected": expected,
        }

    def close_session(self, *, session_uuid: str, closing_balance) -> dict:
        session = self.db.query_one(
            "SELECT * FROM cash_sessions WHERE uuid=? AND status='OPEN'",
            (session_uuid,),
        )
        if session is None:
            raise SessionError("لا توجد وردية مفتوحة بهذا المعرف")
        counted = D(str(closing_balance).replace(",", ""))
        summary = self.cash_summary(session)
        discrepancy = counted - summary["expected"]
        self.db.execute(
            "UPDATE cash_sessions SET closed_at=?, closing_balance=?,"
            " expected_balance=?, discrepancy=?, status='CLOSED'"
            " WHERE uuid=?",
            (_now_iso(), money(counted), money(summary["expected"]),
             money(discrepancy), session_uuid),
        )
        tenant_id = session["tenant_id"]
        device_id = session["device_id"]
        self.outbox.append(
            tenant_id=tenant_id,
            device_id=device_id,
            event_type="cash.session_closed",
            payload={
                "version": 1,
                "session_uuid": session_uuid,
                "opening": money(summary["opening"]),
                "cash_in": money(summary["cash_in"]),
                "cash_out": money(summary["cash_out"]),
                "expected": money(summary["expected"]),
                "counted": money(counted),
                "discrepancy": money(discrepancy),
            },
        )
        return {
            "expected": money(summary["expected"]),
            "counted": money(counted),
            "discrepancy": money(discrepancy),
        }
