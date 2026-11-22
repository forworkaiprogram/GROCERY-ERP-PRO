"""Sales history: local invoices + item viewer + text receipt preview."""

from __future__ import annotations

from decimal import Decimal

from PySide6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ..i18n import tr
from .common import ListScreen, money_text


class SalesScreen(ListScreen):
    def __init__(self, runtime, language: str):
        super().__init__(runtime, language)
        self._setup_table(
            ["invoice_no", "date", "customer", "total", "status"]
        )
        actions = QHBoxLayout()
        view = QPushButton(tr(language, "view_items"))
        view.clicked.connect(self._view_items)
        preview = QPushButton(tr(language, "preview_invoice"))
        preview.clicked.connect(self._preview_invoice)
        actions.addWidget(view)
        actions.addWidget(preview)
        actions.addStretch(1)
        self.layout().addLayout(actions)
        self.reload()

    def _source_rows(self, term: str):
        clause = ""
        params: tuple = ()
        if term:
            clause = " AND invoice_no LIKE ?"
            params = (f"%{term}%",)
        return self.runtime.db.query_all(
            "SELECT uuid, invoice_no, created_at, customer_uuid,"
            " total, status FROM sales WHERE tenant_id=?" + clause +
            " ORDER BY created_at DESC LIMIT 300",
            (self._tenant_id(), *params),
        )

    def reload(self) -> None:
        rows = self._source_rows(self.search.text().strip())
        names = {
            c["uuid"]: c["name"]
            for c in self.runtime.db.query_all(
                "SELECT uuid, name FROM customers"
            )
        }
        view = []
        self._uuids = []
        for r in rows:
            self._uuids.append(r["uuid"])
            customer = "—"
            if r["customer_uuid"]:
                customer = names.get(r["customer_uuid"], "?")
            view.append([
                r["invoice_no"],
                (r["created_at"] or "")[:19],
                customer,
                money_text(Decimal(r["total"])),
                r["status"],
            ])
        self._show_rows(view)

    def _selected_sale(self) -> dict | None:
        row = self.table.currentRow()
        if row < 0 or row >= len(self._uuids):
            return None
        sale_uuid = self._uuids[row]
        return self.runtime.db.query_one(
            "SELECT * FROM sales WHERE uuid=?", (sale_uuid,)
        )

    def _items_of(self, sale_uuid: str):
        items = self.runtime.db.query_all(
            "SELECT * FROM sale_items WHERE sale_uuid=?", (sale_uuid,)
        )
        names = {}
        for p in self.runtime.db.query_all("SELECT uuid, name, name_ar FROM products"):
            names[p["uuid"]] = p["name_ar"] or p["name"]
        return [dict(i) | {"product_name": names.get(i["product_uuid"], "?")} for i in items]

    def _view_items(self) -> None:
        sale = self._selected_sale()
        if sale is None:
            QMessageBox.information(
                self, tr(self.language, "sales"),
                tr(self.language, "choose_backup").replace(
                    tr(self.language, "choose_backup"),
                    tr(self.language, "admin_only") if False else tr(self.language, "admin_only")
                ) if False else tr(self.language, "select_invoice"),
            )
            return
        dialog = QWidget()
        dialog.setWindowTitle(f"{tr(self.language, 'view_items')} — {sale['invoice_no']}")
        dialog.setMinimumWidth(460)
        layout = QVBoxLayout(dialog)
        table = QTableWidget(0, 4)
        table.setHorizontalHeaderLabels([
            tr(self.language, "product"), tr(self.language, "qty"),
            tr(self.language, "unit_price"), tr(self.language, "line_total"),
        ])
        table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        sale_items = self._items_of(sale["uuid"])
        table.setRowCount(len(sale_items))
        for r, item in enumerate(sale_items):
            for c, value in enumerate([
                item["product_name"], str(item["quantity"]),
                money_text(Decimal(item["unit_price"])),
                money_text(Decimal(item["line_total"])),
            ]):
                table.setItem(r, c, QTableWidgetItem(value))
        layout.addWidget(table)
        summary = QLabel(money_text(Decimal(sale["total"])))
        layout.addWidget(summary)
        dialog.show()

    def _preview_invoice(self) -> None:
        sale = self._selected_sale()
        if sale is None:
            return
        dialog = QWidget()
        dialog.setWindowTitle(
            f"{tr(self.language, 'preview_invoice')} — {sale['invoice_no']}"
        )
        dialog.setMinimumSize(420, 500)
        layout = QVBoxLayout(dialog)
        text = QTextEdit()
        text.setReadOnly(True)
        payments = self.runtime.db.query_all(
            "SELECT method, amount FROM payments WHERE payment_type='SALE'"
            " AND reference_uuid=?",
            (sale["uuid"],),
        )
        lines = [
            "===== فاتورة مبيعات =====",
            f"رقم الفاتورة: {sale['invoice_no']}",
            f"التاريخ: {sale['created_at'][:19]}",
            "-" * 32,
        ]
        for item in self._items_of(sale["uuid"]):
            lines.append(
                f"{item['product_name']} — {item['quantity']} × "
                f"{money_text(Decimal(item['unit_price']))} = "
                f"{money_text(Decimal(item['line_total']))}"
            )
        lines.append("-" * 32)
        lines.append(f"الإجمالي: {money_text(Decimal(sale['total']))} YER")
        for p in payments:
            lines.append(f"الدفع [{p['method']}]: {money_text(Decimal(p['amount']))} YER")
        lines.append("شكرًا لزيارتكم!")
        text.setText("\n".join(lines))
        layout.addWidget(text)
        dialog.show()
