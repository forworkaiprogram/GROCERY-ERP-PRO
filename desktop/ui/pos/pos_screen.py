"""POS screen — the primary cashier surface (Arabic-first RTL).

Local-first: F12 commits sale + outbox events in ONE local SQLite
transaction before anything is reported as saved. Cloud is never a
condition of the local commit.
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

from ..i18n import tr
from ..screens.common import money_text

PAYMENT_METHODS = ["CASH", "CARD", "CREDIT", "WALLET", "BANK"]


class PosScreen(QWidget):
    def __init__(self, runtime, language: str = "ar", user: dict | None = None):
        super().__init__()
        self.runtime = runtime
        self.language = language
        self.user = user or {}
        self.cart: list[dict] = []
        self.customer: dict | None = None
        self._sessions = runtime.sessions if hasattr(runtime, "sessions") else None
        if self._sessions is None:
            from ...business_logic.cash_sessions import CashSessionService

            self._sessions = CashSessionService(runtime.db)

        layout = QVBoxLayout(self)

        header = QLabel(f"🛒 {tr(language, 'pos')}")
        header.setObjectName("pageHeader")
        layout.addWidget(header)

        top = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText(tr(language, "scan_hint"))
        self.search.returnPressed.connect(self._on_scan)
        top.addWidget(self.search, 4)

        self.customer_combo = QComboBox()
        self.customer_combo.addItem(tr(language, "walk_in"), None)
        self._load_customers()
        self.customer_combo.currentIndexChanged.connect(self._on_customer)
        top.addWidget(self.customer_combo, 3)
        layout.addLayout(top)

        mid = QHBoxLayout()
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels([
            tr(language, "product"),
            tr(language, "qty"),
            tr(language, "unit_price"),
            tr(language, "tax"),
            tr(language, "line_total"),
        ])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        mid.addWidget(self.table, 4)

        side = QVBoxLayout()
        self.shift_label = QLabel("")
        self.shift_label.setObjectName("card")
        self.shift_label.setWordWrap(True)
        side.addWidget(self.shift_label)

        totals = QFormLayout()
        self.subtotal_label = QLabel("0.00")
        self.tax_label = QLabel("0.00")
        self.total_label = QLabel("0.00")
        self.total_label.setStyleSheet("font-size:17px; font-weight:bold;")
        totals.addRow(tr(language, "subtotal"), self.subtotal_label)
        totals.addRow(tr(language, "tax"), self.tax_label)
        totals.addRow(tr(language, "grand_total"), self.total_label)
        side.addLayout(totals)

        paid_form = QFormLayout()
        self.method = QComboBox()
        self.method.addItems(PAYMENT_METHODS)
        self.paid_edit = QLineEdit("0")
        self.paid_edit.textChanged.connect(self._on_paid_changed)
        self.change_label = QLabel("0.00")
        paid_form.addRow(tr(language, "payment_method"), self.method)
        paid_form.addRow(tr(language, "paid_amount"), self.paid_edit)
        paid_form.addRow(tr(language, "change"), self.change_label)
        side.addLayout(paid_form)
        mid.addLayout(side, 2)
        layout.addLayout(mid, 5)

        cart_buttons = QHBoxLayout()
        plus = QPushButton("+")
        plus.setFixedWidth(48)
        plus.clicked.connect(lambda: self._adjust_selected(1))
        minus = QPushButton("−")
        minus.setFixedWidth(48)
        minus.clicked.connect(lambda: self._adjust_selected(-1))
        remove = QPushButton(tr(language, "remove_line"))
        remove.clicked.connect(self._remove_selected)
        clear = QPushButton(tr(language, "clear_cart"))
        clear.clicked.connect(self._clear)
        cart_buttons.addWidget(plus)
        cart_buttons.addWidget(minus)
        cart_buttons.addWidget(remove)
        cart_buttons.addStretch(1)
        cart_buttons.addWidget(clear)
        layout.addLayout(cart_buttons)

        commit = QPushButton(tr(language, "commit_sale"))
        commit.setObjectName("logoutBtn")
        commit.clicked.connect(self._on_commit)
        layout.addWidget(commit)

        QShortcut(QKeySequence("F2"), self, activated=self.search.setFocus)
        QShortcut(QKeySequence("F12"), self, activated=self._on_commit)

        self._refresh_shift()

    # ---- data loading ----------------------------------------------------
    def _load_customers(self) -> None:
        tenant = self._tenant_id()
        rows = self.runtime.db.query_all(
            "SELECT uuid, name, credit_limit, balance, discount_bps"
            " FROM customers WHERE tenant_id=? ORDER BY name LIMIT 1000",
            (tenant,),
        )
        for row in rows:
            label = row["name"]
            if row["balance"] and row["balance"] != "0.00":
                from decimal import Decimal as _D

                label = f"{label} — {tr(self.language, 'balance')}: {money_text(_D(row['balance']))}"
            self.customer_combo.addItem(label, row["uuid"])

    def _on_customer(self, index: int) -> None:
        uuid = self.customer_combo.itemData(index)
        self.cart = []
        self._refresh()
        if not uuid:
            self.customer = None
            return
        row = self.runtime.db.query_one(
            "SELECT uuid, credit_limit, balance, discount_bps FROM customers"
            " WHERE uuid=?",
            (uuid,),
        )
        self.customer = dict(row) if row else None

    def _refresh_shift(self) -> None:
        session = self._sessions.current_open(self._device_id())
        if session is None:
            self.shift_label.setText(f"📋 {tr(self.language, 'no_shift')}")
            return
        summary = self._sessions.cash_summary(session)
        self.shift_label.setText(
            f"🧾 {tr(self.language, 'current_shift')}\n"
            f"{tr(self.language, 'opening_balance')}: {money_text(summary['opening'])}\n"
            f"{tr(self.language, 'cash_in')}: {money_text(summary['cash_in'])}"
        )

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
            QMessageBox.warning(
                self, tr(self.language, "error"),
                f"{tr(self.language, 'no_product')}: {term}",
            )
            return
        existing = next(
            (c for c in self.cart if c["product_uuid"] == product["uuid"]), None
        )
        if existing:
            existing["quantity"] += Decimal("1")
        else:
            self.cart.append(
                {"product_uuid": product["uuid"], "quantity": Decimal("1"),
                 "unit": "PIECE"}
            )
        self.search.clear()
        self.search.setFocus()
        self._refresh()

    def _adjust_selected(self, delta: int) -> None:
        row = self.table.currentRow()
        if row < 0 or row >= len(self.cart):
            return
        item = self.cart[row]
        new_qty = item["quantity"] + Decimal(delta)
        if new_qty <= 0:
            self.cart.pop(row)
        else:
            item["quantity"] = new_qty
        self._refresh()

    def _remove_selected(self) -> None:
        row = self.table.currentRow()
        if row < 0 or row >= len(self.cart):
            return
        self.cart.pop(row)
        self._refresh()

    def _refresh(self) -> None:
        self.table.setRowCount(len(self.cart))
        subtotal = Decimal("0")
        tax = Decimal("0")
        total = Decimal("0")
        for r, item in enumerate(self.cart):
            product = self.runtime.products.get(self._tenant_id(), item["product_uuid"])
            priced = self.runtime.sales.price_cart(
                tenant_id=self._tenant_id(), items=[item], customer=self.customer
            )[0]
            values = [
                product["name_ar"] or product["name"],
                str(item["quantity"]),
                money_text(priced.unit_price),
                money_text(priced.tax_amount),
                money_text(priced.line_total),
            ]
            for c, value in enumerate(values):
                cell = QTableWidgetItem(value)
                cell.setFlags(cell.flags() & ~Qt.ItemIsEditable)
                cell.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.table.setItem(r, c, cell)
            subtotal += priced.unit_price * priced.quantity
            tax += priced.tax_amount
            total += priced.line_total
        self.subtotal_label.setText(money_text(subtotal))
        self.tax_label.setText(money_text(tax))
        self.total_label.setText(money_text(total))
        self._on_paid_changed()

    def _on_paid_changed(self) -> None:
        try:
            paid = Decimal((self.paid_edit.text() or "0").replace(",", ""))
        except Exception:
            paid = Decimal("0")
        total = self._cart_total() if self.cart else Decimal("0")
        if self.method.currentText() == "CASH" and paid >= total:
            self.change_label.setText(money_text(paid - total))
        else:
            self.change_label.setText("0.00")

    def _on_commit(self) -> None:
        if not self.cart:
            QMessageBox.information(
                self, tr(self.language, "pos"), tr(self.language, "cart_empty")
            )
            return
        total = self._cart_total()
        method = self.method.currentText()
        if method == "CASH":
            paid = Decimal((self.paid_edit.text() or "0").replace(",", "") or "0")
            if paid == 0:
                paid = total
                self.paid_edit.setText(str(total))
                self._on_paid_changed()
            if paid < total:
                QMessageBox.warning(
                    self, tr(self.language, "sale_not_saved"),
                    tr(self.language, "paid_minus_total"),
                )
                return
        payments = [{"method": method, "amount": str(total)}]
        try:
            result = self.runtime.sales.commit_sale(
                tenant_id=self._tenant_id(),
                branch_id=self._branch_id(),
                device_id=self._device_id(),
                cashier_id=self._cashier_id(),
                items=self.cart,
                payments=payments,
                customer=self.customer,
            )
        except Exception as exc:
            QMessageBox.critical(
                self,
                tr(self.language, "sale_not_saved"),
                tr(self.language, "sale_not_saved") + "\n\n" + str(exc),
            )
            return
        self._clear()
        self._refresh_shift()
        QMessageBox.information(
            self,
            tr(self.language, "saved_locally"),
            f"{result['invoice_no']}\n{tr(self.language, 'sale_saved')}",
        )

    def _clear(self) -> None:
        self.cart = []
        self.paid_edit.setText("0")
        self._refresh()

    def _cart_total(self) -> Decimal:
        if not self.cart:
            return Decimal("0")
        priced = self.runtime.sales.price_cart(
            tenant_id=self._tenant_id(), items=self.cart, customer=self.customer
        )
        return sum((line.line_total for line in priced), Decimal("0"))

    def reload(self) -> None:
        self._load_customers()
        self._refresh_shift()

    # ---- session context ---------------------------------------------------
    def _tenant_id(self) -> str:
        return self.runtime.device.get("tenant_id") or "local"

    def _branch_id(self) -> str:
        return (self.runtime.device.get("branch_id") or "main") if self.runtime.device else "main"

    def _device_id(self) -> str:
        return self.runtime.device["device_id"]

    def _cashier_id(self) -> str:
        return self.user.get("uuid") or self.user.get("username") or "local-cashier"
