"""Suppliers screen (purchasing master data): add suppliers, list balances."""

from __future__ import annotations

import uuid as uuidlib
from decimal import Decimal

from PySide6.QtWidgets import (
    QHBoxLayout,
    QPushButton,
)

from ..i18n import tr
from .common import FormDialog, ListScreen, money_text


class SuppliersScreen(ListScreen):
    def __init__(self, runtime, language: str):
        super().__init__(runtime, language)
        self._setup_table(
            ["name", "phone", "credit_limit", "payment_terms_days", "balance"]
        )
        actions = QHBoxLayout()
        add = QPushButton(tr(language, "add"))
        add.clicked.connect(self._open_add_dialog)
        actions.addWidget(add)
        actions.addStretch(1)
        self.layout().addLayout(actions)
        self.reload()

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

    def reload(self) -> None:
        tenant = self._tenant_id()
        term = self.search.text().strip()
        like = f"%{term}%"
        rows = self.runtime.db.query_all(
            "SELECT name, phone, credit_limit, payment_terms_days, balance"
            " FROM suppliers WHERE tenant_id=? AND name LIKE ?"
            " ORDER BY name LIMIT 500",
            (tenant, like),
        )
        self._show_rows([
            [
                r["name"], r["phone"] or "-",
                money_text(Decimal(r["credit_limit"])),
                str(r["payment_terms_days"]),
                money_text(Decimal(r["balance"])),
            ]
            for r in rows
        ])
