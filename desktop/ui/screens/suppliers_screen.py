"""Suppliers screen (purchasing master data): add suppliers, list balances."""

from __future__ import annotations

import uuid as uuidlib
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

from ...business_logic.settlements import pay_supplier
from ..i18n import tr
from .common import FormDialog, ListScreen, money_text


class SuppliersScreen(ListScreen):
    def __init__(self, runtime, language: str, user: dict | None = None):
        super().__init__(runtime, language)
        self.user = user or {}
        self._setup_table(
            ["name", "phone", "credit_limit", "payment_terms_days", "balance"]
        )
        actions = QHBoxLayout()
        add = QPushButton(tr(language, "add"))
        add.clicked.connect(self._open_add_dialog)
        pay = QPushButton(tr(language, "pay_supplier"))
        pay.clicked.connect(self._open_pay_dialog)
        actions.addWidget(add)
        actions.addWidget(pay)
        actions.addStretch(1)
        self.layout().addLayout(actions)
        self.reload()

    def reload(self) -> None:
        tenant = self._tenant_id()
        term = self.search.text().strip()
        rows = [
            dict(r) for r in self.runtime.db.query_all(
                "SELECT uuid, name, phone, credit_limit, payment_terms_days,"
                " balance FROM suppliers WHERE tenant_id=? ORDER BY name"
                " LIMIT 500",
                (tenant,),
            )
        ]
        self._uuids = [r["uuid"] for r in rows]
        self._rows = rows
        self._show_rows([
            [
                r["name"], r["phone"] or "-",
                money_text(Decimal(r["credit_limit"])),
                str(r["payment_terms_days"]),
                money_text(Decimal(r["balance"])),
            ]
            for r in rows if not term or term.lower() in r["name"].lower()
        ])

    def _open_add_dialog(self) -> None:
        FormDialog(
            self, self.runtime, self.language, "purchasing",
            {
                "name": "name",
                "phone": "phone",
                "address": "address",
                "credit_limit": "credit_limit",
                "payment_terms_days": "payment_terms_days",
            },
            self._create_supplier,
        ).show()

    def _open_pay_dialog(self) -> None:
        row = self.table.currentRow()
        if row < 0 or row >= len(getattr(self, "_rows", [])):
            QMessageBox.information(
                self, tr(self.language, "suppliers"),
                tr(self.language, "admin_only"),
            )
            return
        filters = self.search.text().strip().lower()
        visible = [
            r for r in self._rows
            if not filters or filters in r["name"].lower()
        ]
        if row >= len(visible):
            return
        supplier = visible[row]

        dialog = QWidget(self)
        dialog.setWindowTitle(tr(self.language, "pay_supplier"))
        dialog.setMinimumWidth(400)
        layout = QVBoxLayout(dialog)
        form = QFormLayout()
        amount_edit = QLineEdit()
        method = QComboBox()
        method.addItems(["CASH", "BANK", "CARD", "WALLET"])
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
                result = pay_supplier(
                    self.runtime.db,
                    tenant_id=self._tenant_id(),
                    device_id=self._device_id(),
                    supplier_uuid=supplier["uuid"],
                    amount=amount_edit.text(),
                    method=method.currentText(),
                    paid_by=self._user_uuid(),
                    accounting=self.runtime.accounting,
                    outbox=self.runtime.outbox,
                )
            except Exception as exc:
                QMessageBox.critical(self, tr(self.language, "error"), str(exc))
                return
            QMessageBox.information(
                self, tr(self.language, "suppliers"),
                f"{tr(self.language, 'supplier_payment_done')} — "
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

    def _create_supplier(self, values: dict) -> None:
        if not values["name"]:
            raise ValueError(tr(self.language, "name"))
        self.runtime.suppliers.insert(
            {
                "uuid": str(uuidlib.uuid4()),
                "tenant_id": self._tenant_id(),
                "name": values["name"],
                "phone": values["phone"] or None,
                "address": values["address"] or None,
                "credit_limit": values["credit_limit"] or "0",
                "payment_terms_days": int(values["payment_terms_days"] or "0"),
            }
        )
        self.reload()

