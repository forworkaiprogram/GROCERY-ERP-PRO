"""Expense vouchers screen: cash voucher with double-entry posting."""

from __future__ import annotations

from decimal import Decimal

from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ...business_logic.expenses import record_expense
from ..i18n import tr
from .common import ListScreen, money_text


class ExpensesScreen(ListScreen):
    def __init__(self, runtime, language: str):
        super().__init__(runtime, language)
        self._setup_table(
            ["date", "category", "amount", "payment_method", "paid_to"]
        )
        actions = QHBoxLayout()
        add = QPushButton(tr(language, "new_expense"))
        add.clicked.connect(self._open_voucher_dialog)
        actions.addWidget(add)
        actions.addStretch(1)
        self.layout().addLayout(actions)
        self.reload()

    def _source_accounts(self, types: tuple) -> list[tuple]:
        placeholders = ",".join("?" for _ in types)
        return [
            (r["code"], r["name_ar"] or r["name"])
            for r in self.runtime.db.query_all(
                f"SELECT code, name, name_ar FROM accounts WHERE type IN"
                f" ({placeholders}) ORDER BY code",
                types,
            )
        ]

    def _open_voucher_dialog(self) -> None:
        dialog = QWidget(self)
        dialog.setWindowTitle(tr(self.language, "new_expense"))
        dialog.setMinimumWidth(460)
        layout = QVBoxLayout(dialog)
        form = QFormLayout()

        def fill(combo: QComboBox, pairs: list[tuple]) -> None:
            for code, label in pairs:
                combo.addItem(f"{code} - {label}", code)

        category_combo = QComboBox()
        for row in self.runtime.db.query_all(
            "SELECT name, name_ar FROM expense_categories ORDER BY name"
        ):
            category_combo.addItem(row["name_ar"] or row["name"], row["name"])

        account_combo = QComboBox()
        fill(account_combo, self._source_accounts(("EXPENSE",)))
        pay_from_combo = QComboBox()
        fill(pay_from_combo, self._source_accounts(("ASSET",)))
        if pay_from_combo.count() > 1:
            pay_from_combo.setCurrentIndex(1)

        amount_edit = QLineEdit()
        paid_to_edit = QLineEdit()
        method_combo = QComboBox()
        method_combo.addItems(["CASH", "CARD", "BANK", "WALLET"])

        form.addRow(tr(self.language, "category"), category_combo)
        form.addRow(tr(self.language, "amount"), amount_edit)
        form.addRow(tr(self.language, "expense_account"), account_combo)
        form.addRow(tr(self.language, "paid_from"), pay_from_combo)
        form.addRow(tr(self.language, "payment_method"), method_combo)
        form.addRow(tr(self.language, "paid_to"), paid_to_edit)
        layout.addLayout(form)

        buttons = QHBoxLayout()
        save = QPushButton(tr(self.language, "save"))
        cancel = QPushButton(tr(self.language, "cancel"))
        cancel.clicked.connect(dialog.close)

        def submit() -> None:
            try:
                record_expense(
                    self.runtime.db,
                    self.runtime.accounting,
                    self.runtime.outbox,
                    tenant_id=self._tenant_id(),
                    device_id=self.runtime.device["device_id"],
                    category=category_combo.currentData(),
                    amount=amount_edit.text().strip(),
                    paid_from_account=pay_from_combo.currentData(),
                    expense_account=account_combo.currentData(),
                    paid_to=paid_to_edit.text().strip() or None,
                    payment_method=method_combo.currentText(),
                    approved_by="local",
                )
            except Exception as exc:
                QMessageBox.critical(
                    dialog, tr(self.language, "error"),
                    f"{type(exc).__name__}: {exc}",
                )
                return
            QMessageBox.information(
                dialog, tr(self.language, "app_title"), tr(self.language, "saved")
            )
            dialog.close()

        save.clicked.connect(submit)
        buttons.addWidget(save)
        buttons.addWidget(cancel)
        layout.addLayout(buttons)
        dialog.show()

    def reload(self) -> None:
        tenant = self._tenant_id()
        rows = self.runtime.db.query_all(
            "SELECT voucher_date, category, amount, payment_method, paid_to"
            " FROM expense_vouchers WHERE tenant_id=?"
            " ORDER BY voucher_date DESC LIMIT 300",
            (tenant,),
        )
        self._show_rows([
            [
                r["voucher_date"],
                r["category"],
                money_text(Decimal(r["amount"])),
                r["payment_method"],
                r["paid_to"] or "-",
            ]
            for r in rows
        ])
