"""Accounts receivable (debts): customers with balance and payments."""

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

from ...business_logic.settlements import receive_customer_payment
from ..i18n import tr
from .common import ListScreen, money_text


class DebtsScreen(ListScreen):
    def __init__(self, runtime, language: str):
        super().__init__(runtime, language)
        self._setup_table(
            ["name", "phone", "balance", "credit_limit"]
        )
        actions = QHBoxLayout()
        pay = QPushButton(tr(language, "receive_payment"))
        pay.clicked.connect(self._open_payment_dialog)
        actions.addWidget(pay)
        actions.addStretch(1)
        self.layout().addLayout(actions)
        self.reload()

    def reload(self) -> None:
        tenant = self._tenant_id()
        term = self.search.text().strip().lower()
        rows = self.runtime.db.query_all(
            "SELECT uuid, name, phone, balance, credit_limit"
            " FROM customers WHERE tenant_id=? ORDER BY name",
            (tenant,),
        )
        view = []
        self._debtors: dict[str, dict] = {}
        for r in rows:
            balance = Decimal(r["balance"])
            name = r["name"]
            if term and term not in name.lower():
                continue
            if balance == 0:
                continue
            self._debtors[r["uuid"]] = dict(r)
            view.append([
                name, r["phone"] or "-", money_text(balance),
                money_text(Decimal(r["credit_limit"])),
            ])
        self._debt_order = list(self._debtors.keys())
        self._show_rows(view)

    def _selected_debtor(self) -> dict | None:
        row = self.table.currentRow()
        if row < 0 or row >= len(self._debt_order):
            return None
        return self._debtors[self._debt_order[row]]

    def _open_payment_dialog(self) -> None:
        customer = self._selected_debtor()
        if customer is None:
            QMessageBox.information(
                self, tr(self.language, "debts"),
                tr(self.language, "admin_only"),
            )
            return

        dialog = QWidget(self)
        dialog.setWindowTitle(tr(self.language, "receive_payment"))
        dialog.setMinimumWidth(400)
        layout = QVBoxLayout(dialog)
        form = QFormLayout()
        amount_edit = QLineEdit()
        method = QComboBox()
        method.addItems(["CASH", "CARD", "BANK", "WALLET"])
        form.addRow(tr(self.language, "amount"), amount_edit)
        form.addRow(tr(self.language, "payment_method"), method)
        layout.addLayout(form)

        def submit() -> None:
            if not amount_edit.text().strip():
                QMessageBox.warning(
                    self, tr(self.language, "error"),
                    tr(self.language, "enter_all_fields"),
                )
                return
            try:
                result = receive_customer_payment(
                    self.runtime.db,
                    tenant_id=self._tenant_id(),
                    device_id=self._device_id(),
                    customer_uuid=customer["uuid"],
                    amount=amount_edit.text(),
                    method=method.currentText(),
                    received_by=self._user_uuid(),
                    accounting=self.runtime.accounting,
                    outbox=self.runtime.outbox,
                )
            except Exception as exc:
                QMessageBox.critical(self, tr(self.language, "error"), str(exc))
                return
            QMessageBox.information(
                self, tr(self.language, "debts"),
                f"{tr(self.language, 'customer_payment_done')} — "
                f"{tr(self.language, 'balance')}: {result['new_balance']}",
            )
            dialog.close()
            self.reload()

        buttons = QHBoxLayout()
        save = QPushButton(tr(self.language, "save"))
        save.clicked.connect(submit)
        cancel = QPushButton(tr(self.language, "cancel"))
        cancel.clicked.connect(dialog.close)
        buttons.addWidget(save)
        buttons.addWidget(cancel)
        layout.addLayout(buttons)
        dialog.show()
