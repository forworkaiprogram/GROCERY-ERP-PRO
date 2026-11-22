"""Customers screen: add customers and track local balances."""

from __future__ import annotations

import uuid as uuidlib
from decimal import Decimal

from PySide6.QtWidgets import (
    QHBoxLayout,
    QPushButton,
)

from ..i18n import tr
from .common import FormDialog, ListScreen, money_text


class CustomersScreen(ListScreen):
    def __init__(self, runtime, language: str):
        super().__init__(runtime, language)
        self._setup_table(["name", "phone", "group", "credit_limit", "balance"])
        actions = QHBoxLayout()
        add = QPushButton(tr(language, "customers") + f" - {tr(language, 'add')}")
        add.clicked.connect(self._open_add_dialog)
        actions.addWidget(add)
        actions.addStretch(1)
        self.layout().addLayout(actions)
        self.reload()

    def _open_add_dialog(self) -> None:
        FormDialog(
            self, self.runtime, self.language, "customers",
            {
                "name": "name",
                "phone": "phone",
                "address": "address",
                "group": "group",
                "credit_limit": "credit_limit",
            },
            self._create_customer,
        ).show()

    def _create_customer(self, values: dict) -> None:
        if not values["name"]:
            raise ValueError(tr(self.language, "name"))
        self.runtime.customers.insert(
            {
                "uuid": str(uuidlib.uuid4()),
                "tenant_id": self._tenant_id(),
                "name": values["name"],
                "phone": values["phone"] or None,
                "address": values["address"] or None,
                "group_name": values["group"] or None,
                "credit_limit": values["credit_limit"] or "0",
            }
        )
        self.reload()

    def reload(self) -> None:
        tenant = self._tenant_id()
        term = self.search.text().strip()
        like = f"%{term}%"
        rows = self.runtime.db.query_all(
            "SELECT name, phone, group_name, credit_limit, balance FROM customers"
            " WHERE tenant_id=? AND (name LIKE ? OR COALESCE(phone,'') LIKE ?)"
            " ORDER BY name LIMIT 500",
            (tenant, like, like),
        )
        self._show_rows([
            [
                r["name"], r["phone"] or "-", r["group_name"] or "-",
                money_text(Decimal(r["credit_limit"])),
                money_text(Decimal(r["balance"])),
            ]
            for r in rows
        ])
