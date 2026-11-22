"""Double-entry accounting engine (local, provisional until centrally posted).

Rules enforced here and in the V1 schema:
- Every entry must balance: total debits == total credits (Decimal).
- Rows must debit exactly one side (CHECK constraints reject both/neither).
- Posted entries are immutable: corrections are reversal entries only.
- Monetary values are Decimal rendered to 2dp strings; floats are rejected.
"""

from __future__ import annotations

import uuid as uuidlib
from datetime import date
from decimal import Decimal

from .money import D, MoneyError, assert_balanced, money

SOURCE_TYPES = frozenset(
    {"SALE", "EXPENSE", "PAYMENT", "ADJUSTMENT", "OPENING", "PURCHASE"}
)


class AccountingError(ValueError):
    pass


class AccountingEngine:
    def __init__(self, db):
        self.db = db

    def post_entry(
        self,
        *,
        tenant_id: str,
        lines: list[tuple[str, Decimal, Decimal]],
        memo: str,
        source_type: str,
        source_uuid: str | None = None,
        entry_date: date | None = None,
    ) -> dict:
        """Post a balanced journal entry inside the caller's transaction.

        lines: [(account_code, debit, credit), ...]; zero rows are dropped.
        Returns {uuid, entry_no}.
        """
        if source_type not in SOURCE_TYPES:
            raise AccountingError(f"invalid source_type {source_type!r}")

        cleaned: list[tuple[str, Decimal, Decimal]] = []
        debits = Decimal("0")
        credits = Decimal("0")
        for account_code, debit, credit in lines:
            debit, credit = D(debit), D(credit)
            if debit < 0 or credit < 0:
                raise AccountingError("debit/credit cannot be negative")
            if debit > 0 and credit > 0:
                raise AccountingError("a line cannot be both debit and credit")
            if debit == 0 and credit == 0:
                continue
            if not self.db.query_one(
                "SELECT 1 FROM accounts WHERE code = ?", (account_code,)
            ):
                raise AccountingError(f"unknown account {account_code!r}")
            cleaned.append((account_code, debit, credit))
            debits += debit
            credits += credit
        try:
            assert_balanced(debits, credits)
        except MoneyError as exc:
            raise AccountingError(str(exc)) from exc
        if not cleaned:
            raise AccountingError("journal entry has no lines")

        entry_uuid = str(uuidlib.uuid4())
        entry_no = self._next_entry_no(tenant_id)
        self.db.execute(
            "INSERT INTO journal_entries (uuid, tenant_id, entry_no, entry_date,"
            " memo, source_type, source_uuid) VALUES (?,?,?,?,?,?,?)",
            (
                entry_uuid,
                tenant_id,
                entry_no,
                (entry_date or date.today()).isoformat(),
                memo,
                source_type,
                source_uuid,
            ),
        )
        for account_code, debit, credit in cleaned:
            self.db.execute(
                "INSERT INTO journal_lines (entry_uuid, account_code, debit, credit)"
                " VALUES (?,?,?,?)",
                (entry_uuid, account_code, money(debit), money(credit)),
            )
        return {"uuid": entry_uuid, "entry_no": entry_no}

    def post_reversal(self, *, tenant_id: str, entry_uuid: str, memo: str) -> dict:
        """Reverse an existing entry by posting the mirrored entry. The
        original row's content is never mutated; its status flag becomes
        'REVERSED' so it is excluded from statement computations."""
        entry = self.db.query_one(
            "SELECT * FROM journal_entries WHERE uuid = ? AND tenant_id = ?",
            (entry_uuid, tenant_id),
        )
        if entry is None:
            raise AccountingError("journal entry not found")
        if entry["status"] == "REVERSED":
            raise AccountingError("entry is already reversed")
        lines = self.db.query_all(
            "SELECT account_code, debit, credit FROM journal_lines WHERE entry_uuid = ?",
            (entry_uuid,),
        )
        reversed_lines = [
            (row["account_code"], D(row["credit"]), D(row["debit"])) for row in lines
        ]
        result = self.post_entry(
            tenant_id=tenant_id,
            lines=reversed_lines,
            memo=f"Reversal of {entry['entry_no']}: {memo}",
            source_type=entry["source_type"],
            source_uuid=entry["source_uuid"],
        )
        self.db.execute(
            "UPDATE journal_entries SET status='REVERSED', reversal_of=? WHERE uuid=?"
            " AND status <> 'REVERSED'",
            (entry_uuid, entry_uuid),
        )
        return result

    def trial_balance(self, tenant_id: str) -> dict:
        # Sums are computed in Python with Decimal: SQLite SUM on TEXT
        # returns floats, which are prohibited for monetary arithmetic.
        rows = self.db.query_all(
            "SELECT l.account_code, a.type, l.debit, l.credit"
            " FROM journal_lines l JOIN journal_entries e ON e.uuid = l.entry_uuid"
            " LEFT JOIN accounts a ON a.code = l.account_code"
            " WHERE e.tenant_id = ? AND e.status <> 'REVERSED'"
            " ORDER BY l.account_code",
            (tenant_id,),
        )
        result: dict[str, dict] = {}
        type_by_code: dict[str, str | None] = {}
        for r in rows:
            code = r["account_code"]
            slot = result.setdefault(code, {"type": r["type"], "debits": Decimal("0"), "credits": Decimal("0")})
            type_by_code[code] = r["type"]
            slot["debits"] += D(r["debit"])
            slot["credits"] += D(r["credit"])
        return result

    def _next_entry_no(self, tenant_id: str) -> str:
        row = self.db.query_one(
            "SELECT COUNT(*) AS n FROM journal_entries WHERE tenant_id = ?",
            (tenant_id,),
        )
        today = date.today().isoformat().replace("-", "")
        return f"JE-{today}-{int(row['n']) + 1:06d}"

    def entry_payload(self, entry_uuid: str, payload_version: int = 1) -> dict:
        """Canonical payload for the sync outbox."""
        entry = self.db.query_one(
            "SELECT * FROM journal_entries WHERE uuid = ?", (entry_uuid,)
        )
        lines = self.db.query_all(
            "SELECT account_code, debit, credit FROM journal_lines WHERE entry_uuid = ?"
            " ORDER BY id",
            (entry_uuid,),
        )
        return {
            "schema": "journal_entry",
            "version": payload_version,
            "uuid": entry["uuid"],
            "entry_no": entry["entry_no"],
            "entry_date": entry["entry_date"],
            "memo": entry["memo"],
            "source_type": entry["source_type"],
            "source_uuid": entry["source_uuid"],
            "lines": [
                {
                    "account_code": r["account_code"],
                    "debit": r["debit"],
                    "credit": r["credit"],
                }
                for r in lines
            ],
        }
