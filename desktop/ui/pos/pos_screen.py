"""POS screen — the primary cashier surface.

Wired to the local SaleEngine: commit is synchronous-local (one SQLite
transaction including the outbox events) then the UI reports success.
Cloud acknowledgement is shown separately through sync_state; it is never
a condition of saving. The barcode/search line-edit is the keyboard-first
flow for scanners.
"""

from __future__ import annotations

from decimal import Decimal

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)


class PosScreen(QWidget):
    def __init__(self, runtime):
        super().__init__()
        self.runtime = runtime
        self.cart: list[dict] = []
        self.customer = None

        layout = QVBoxLayout(self)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Scan barcode or search product…")
        self.search.returnPressed.connect(self._on_scan)
        layout.addWidget(self.search)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            ["Product", "Qty", "Unit price", "Discount", "Line total"]
        )
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        layout.addWidget(self.table, 4)

        totals = QFormLayout()
        self.subtotal_label = QLabel("0.00")
        self.tax_label = QLabel("0.00")
        self.total_label = QLabel("0.00")
        totals.addRow("Subtotal:", self.subtotal_label)
        totals.addRow("Tax:", self.tax_label)
        totals.addRow("TOTAL:", self.total_label)
        layout.addLayout(totals)

        actions = QHBoxLayout()
        self.method = QComboBox()
        self.method.addItems(["CASH", "CARD", "CREDIT", "WALLET", "BANK"])
        self.pay_button = QPushButton("Commit sale (F12)")
        self.pay_button.clicked.connect(self._on_commit)
        self.clear_button = QPushButton("Clear cart")
        self.clear_button.clicked.connect(self._clear)
        actions.addWidget(self.method)
        actions.addWidget(self.pay_button)
        actions.addWidget(self.clear_button)
        layout.addLayout(actions)

        QShortcut(QKeySequence("F12"), self, activated=self._on_commit)

    # ---- cart handling ---------------------------------------------------
    def _on_scan(self) -> None:
        term = self.search.text().strip()
        if not term:
            return
        tenant = self._tenant_id()
        product = self.runtime.products.by_barcode(tenant, term)
        if product is None:
            product = self.runtime.products.by_sku(tenant, term)
        if product is None:
            matches = self.runtime.products.search(tenant, term)
            product = matches[0] if matches else None
        if product is None:
            QMessageBox.warning(self, "POS", f"No product matches {term!r}")
            return
        existing = next(
            (c for c in self.cart if c["product_uuid"] == product["uuid"]), None
        )
        if existing:
            existing["quantity"] += Decimal("1")
        else:
            self.cart.append(
                {"product_uuid": product["uuid"], "quantity": Decimal("1"), "unit": "PIECE"}
            )
        self.search.clear()
        self._refresh()

    def _refresh(self) -> None:
        tenant = self._tenant_id()
        self.table.setRowCount(len(self.cart))
        subtotal = Decimal("0")
        tax = Decimal("0")
        total = Decimal("0")
        for r, item in enumerate(self.cart):
            product = self.runtime.products.get(tenant, item["product_uuid"])
            priced = self.runtime.sales.price_cart(
                tenant_id=tenant, items=[item], customer=self.customer
            )[0]
            values = [
                product["name"],
                str(item["quantity"]),
                str(priced.unit_price),
                str(priced.discount),
                str(priced.line_total),
            ]
            for c, value in enumerate(values):
                cell = QTableWidgetItem(value)
                cell.setFlags(cell.flags() & ~Qt.ItemIsEditable)
                self.table.setItem(r, c, cell)
            subtotal += priced.unit_price * priced.quantity
            tax += priced.tax_amount
            total += priced.line_total
        self.subtotal_label.setText(f"{subtotal:.2f}")
        self.tax_label.setText(f"{tax:.2f}")
        self.total_label.setText(f"{total:.2f}")

    def _on_commit(self) -> None:
        if not self.cart:
            QMessageBox.information(self, "POS", "Cart is empty")
            return
        try:
            result = self.runtime.sales.commit_sale(
                tenant_id=self._tenant_id(),
                branch_id=self._branch_id(),
                device_id=self._device_id(),
                cashier_id=self._cashier_id(),
                items=self.cart,
                payments=[{"method": self.method.currentText(), "amount": self._cart_total()}],
                customer=self.customer,
            )
        except Exception as exc:
            QMessageBox.critical(
                self,
                "Sale not saved",
                "The sale was NOT saved (local commit failed).\n\n" + str(exc),
            )
            return
        self._clear()
        QMessageBox.information(
            self,
            "Sale saved locally",
            f"Invoice {result['invoice_no']} saved locally for {result['total']}.\n"
            "It will synchronize automatically in the background.",
        )

    def _clear(self) -> None:
        self.cart = []
        self._refresh()

    def _cart_total(self) -> Decimal:
        priced = self.runtime.sales.price_cart(
            tenant_id=self._tenant_id(), items=self.cart, customer=self.customer
        )
        return sum((line.line_total for line in priced), Decimal("0"))

    # ---- session context --------------------------------------------------
    def _tenant_id(self) -> str:
        return self.runtime.device.get("tenant_id") or "local"

    def _branch_id(self) -> str:
        return (self.runtime.device.get("branch_id") or "main") if self.runtime.device else "main"

    def _device_id(self) -> str:
        return self.runtime.device["device_id"]

    def _cashier_id(self) -> str:
        return "local-cashier"
