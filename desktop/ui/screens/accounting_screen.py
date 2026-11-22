"""Accounting screen: trial balance (local, Decimal-exact)."""

from __future__ import annotations

from decimal import Decimal

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..i18n import tr
from .common import money_text

TYPES_AR = {
    "ASSET": "أصول", "LIABILITY": "التزامات", "EQUITY": "حقوق ملكية",
    "REVENUE": "إيرادات", "EXPENSE": "مصروفات",
}


class AccountingScreen(QWidget):
    def __init__(self, runtime, language: str):
        super().__init__()
        self.runtime = runtime
        self.language = language
        layout = QVBoxLayout(self)

        self.summary = QLabel("")
        layout.addWidget(self.summary)

        layout.addWidget(
            QLabel(f"<b>{tr(language, 'debits')} / {tr(language, 'credits')}</b>")
        )
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels([
            tr(language, "account_code"), tr(language, "account_name"),
            tr(language, "account_type"), tr(language, "debits"),
            tr(language, "credits"),
        ])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        layout.addWidget(self.table, 4)
        self.reload()

    def _tenant_id(self) -> str:
        if self.runtime.device:
            return self.runtime.device.get("tenant_id") or "local"
        return "local"

    def reload(self) -> None:
        tenant = self._tenant_id()
        balance = self.runtime.accounting.trial_balance(tenant)

        names: dict[str, tuple[str, str]] = {
            r["code"]: (r["name"], r["name_ar"] or "")
            for r in self.runtime.db.query_all(
                "SELECT code, name, name_ar FROM accounts"
            )
        }
        total_debits = sum(
            (slot["debits"] for slot in balance.values()), Decimal("0")
        )
        total_credits = sum(
            (slot["credits"] for slot in balance.values()), Decimal("0")
        )
        state = "ميزان متوازن ✔" if total_debits == total_credits else "غير متوازن ✖"
        self.summary.setText(
            f"{tr(self.language, 'debits')}: {money_text(total_debits)}"
            f"  |  {tr(self.language, 'credits')}: {money_text(total_credits)}"
            f"  |  {state}"
        )

        self.table.setRowCount(len(balance))
        for row_index, (code, slot) in enumerate(sorted(balance.items())):
            account_name, name_ar = names.get(code, (code, ""))
            values = [
                code,
                name_ar or account_name,
                TYPES_AR.get(slot["type"], slot["type"] or ""),
                money_text(slot["debits"]),
                money_text(slot["credits"]),
            ]
            for c, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.table.setItem(row_index, c, item)
