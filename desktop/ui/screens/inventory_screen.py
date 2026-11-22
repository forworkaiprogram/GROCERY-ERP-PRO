"""Inventory screen: balance projection + auditable stock receipt.

Receiving stock appends a PURCHASE_RECEIPT movement to the append-only
ledger inside one transaction, then queues an inventory.movement outbox
event, exactly like sale-time movements.
"""

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

from ..i18n import tr
from .common import ListScreen, money_text, qty_text


class InventoryScreen(ListScreen):
    def __init__(self, runtime, language: str):
        super().__init__(runtime, language)
        self._setup_table(["product", "branch", "qty", "reserved", "cost_value"])
        actions = QHBoxLayout()
        receive = QPushButton(tr(language, "receive_stock"))
        receive.clicked.connect(self._open_receive_dialog)
        actions.addWidget(receive)
        actions.addStretch(1)
        self.layout().addLayout(actions)
        self.reload()

    def _open_receive_dialog(self) -> None:
        dialog = QWidget(self)
        dialog.setWindowTitle(tr(self.language, "receive_stock"))
        dialog.setMinimumWidth(420)
        layout = QVBoxLayout(dialog)
        form = QFormLayout()

        product_combo = QComboBox()
        for p in self.runtime.db.query_all(
            "SELECT uuid, name, name_ar, sku FROM products WHERE tenant_id=?"
            " AND status='ACTIVE' ORDER BY name",
            (self._tenant_id(),),
        ):
            label = f"{p['name_ar'] or p['name']} ({p['sku']})"
            product_combo.addItem(label, p["uuid"])

        qty_edit = QLineEdit()
        cost_edit = QLineEdit()
        form.addRow(tr(self.language, "product"), product_combo)
        form.addRow(tr(self.language, "qty"), qty_edit)
        form.addRow(tr(self.language, "cost"), cost_edit)
        layout.addLayout(form)

        buttons = QHBoxLayout()
        save = QPushButton(tr(self.language, "save"))
        cancel = QPushButton(tr(self.language, "cancel"))
        cancel.clicked.connect(dialog.close)

        def submit() -> None:
            try:
                self._receive(
                    product_combo.currentData(), qty_edit.text().strip(),
                    cost_edit.text().strip() or None,
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

    def _receive(self, product_uuid, quantity: str, cost) -> None:
        if not product_uuid:
            raise ValueError(tr(self.language, "product"))
        decimal_qty = Decimal(quantity)
        if decimal_qty <= 0:
            raise ValueError(tr(self.language, "qty"))
        tenant = self._tenant_id()
        branch = (
            self.runtime.device.get("branch_id") or "main"
        ) if self.runtime.device else "main"
        device_id = self.runtime.device["device_id"]
        with self.runtime.db.transaction():
            result = self.runtime.inventory.record_movement(
                tenant_id=tenant,
                branch_id=branch,
                product_uuid=product_uuid,
                movement_type="PURCHASE_RECEIPT",
                direction=1,
                quantity=decimal_qty,
                unit="PIECE",
                cost=cost,
                reference_type="PURCHASE",
                created_by="local",
            )
            self.runtime.outbox.append(
                tenant_id=tenant,
                device_id=device_id,
                event_type="inventory.movement",
                payload=self.runtime.inventory.movement_payload(result["uuid"]),
            )
        self.reload()

    def reload(self) -> None:
        tenant = self._tenant_id()
        term = self.search.text().strip()
        like = f"%{term}%"
        rows = self.runtime.db.query_all(
            "SELECT b.branch_id, b.quantity, b.reserved_qty,"
            " p.name, p.name_ar, p.cost FROM inventory_balances b"
            " JOIN products p ON p.uuid = b.product_uuid"
            " WHERE b.tenant_id=? AND p.name LIKE ?"
            " ORDER BY p.name LIMIT 500",
            (tenant, like),
        )
        view = []
        for r in rows:
            quantity = Decimal(r["quantity"])
            cost_value = quantity * Decimal(r["cost"])
            view.append([
                r["name_ar"] or r["name"],
                r["branch_id"],
                qty_text(quantity),
                qty_text(Decimal(r["reserved_qty"])),
                money_text(cost_value),
            ])
        self._show_rows(view)
