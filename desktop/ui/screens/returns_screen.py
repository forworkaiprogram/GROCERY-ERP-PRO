"""Returns screen: pick an invoice, enter per-line return quantities."""

from __future__ import annotations

from decimal import Decimal

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
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

from ...business_logic.returns import return_sale
from ..i18n import tr
from .common import SessionContextMixin
from .common import money_text

QTY_ROLE = Qt.UserRole + 1


class ReturnsScreen(SessionContextMixin, QWidget):
    def __init__(self, runtime, language: str, user: dict | None = None):
        super().__init__()
        self.runtime = runtime
        self.language = language
        self.user = user or {}
        self._sale = None

        layout = QVBoxLayout(self)
        header = QLabel(f"↩ {tr(language, 'returns')}")
        header.setObjectName("pageHeader")
        layout.addWidget(header)

        finder = QHBoxLayout()
        finder.addWidget(QLabel(tr(language, "select_invoice")))
        self.search = QLineEdit()
        self.search.setPlaceholderText("INV-XXXXXXXX-0000001")
        finder.addWidget(self.search, 2)
        load = QPushButton(tr(language, "load"))
        load.clicked.connect(self._load_invoice)
        finder.addWidget(load)
        layout.addLayout(finder)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels([
            tr(language, "product"), tr(language, "sold_qty"),
            tr(language, "returned_qty"), tr(language, "remaining"),
            tr(language, "return_qty"),
        ])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        layout.addWidget(self.table, 4)

        reason_row = QHBoxLayout()
        reason_row.addWidget(QLabel(tr(language, "reason")))
        self.reason = QLineEdit()
        reason_row.addWidget(self.reason, 2)
        enter = QPushButton(tr(language, "new_return"))
        enter.clicked.connect(self._submit)
        reason_row.addWidget(enter)
        reason_row.addStretch(1)
        layout.addLayout(reason_row)

    def _load_invoice(self) -> None:
        invoice = self.search.text().strip()
        if not invoice:
            return
        sale = self.runtime.db.query_one(
            "SELECT * FROM sales WHERE invoice_no=? AND tenant_id=?",
            (invoice, self._tenant_id()),
        )
        if sale is None:
            self._sale = None
            QMessageBox.warning(
                self, tr(self.language, "error"),
                tr(self.language, "invoice_not_found"),
            )
            return
        self._sale = sale
        items = self.runtime.db.query_all(
            "SELECT * FROM sale_items WHERE sale_uuid=?", (sale["uuid"],)
        )
        names = {
            p["uuid"]: (p["name_ar"] or p["name"])
            for p in self.runtime.db.query_all(
                "SELECT uuid, name, name_ar FROM products"
            )
        }
        self.table.setRowCount(len(items))
        self._lines = []
        for r, item in enumerate(items):
            sold = Decimal(item["quantity"])
            already = self._returned_qty(sale["uuid"], item["id"])
            remaining = sold - already
            product_name = names.get(item["product_uuid"], "?")
            for c, value in enumerate([
                product_name, str(sold), str(already), str(remaining), "0",
            ]):
                cell = QTableWidgetItem(value)
                self.table.setItem(r, c, cell)
            self.table.item(r, 0).setFlags(cell.flags() & ~Qt.ItemIsEditable)
            self.table.item(r, 1).setFlags(cell.flags() & ~Qt.ItemIsEditable)
            self.table.item(r, 2).setFlags(cell.flags() & ~Qt.ItemIsEditable)
            self.table.item(r, 3).setFlags(cell.flags() & ~Qt.ItemIsEditable)
            self.table.item(r, 3).setData(QTY_ROLE, str(remaining))
            self._lines.append({"sale_item_id": item["id"], "row": r})

    def _returned_qty(self, sale_uuid: str, sale_item_id: str) -> Decimal:
        rows = self.runtime.db.query_all(
            "SELECT ri.quantity AS qty FROM return_items ri"
            " JOIN returns rt ON rt.uuid = ri.return_uuid"
            " WHERE rt.sale_uuid=? AND ri.sale_item_id=?",
            (sale_uuid, sale_item_id),
        )
        return sum((Decimal(r["qty"]) for r in rows), Decimal("0"))

    def _submit(self) -> None:
        if self._sale is None:
            QMessageBox.information(
                self, tr(self.language, "returns"),
                tr(self.language, "select_invoice"),
            )
            return
        items = []
        for line in self._lines:
            cell = self.table.item(line["row"], 4)
            entered = (cell.text() or "0").strip() if cell else "0"
            if not entered or Decimal(entered) == 0:
                continue
            remaining = Decimal(self.table.item(line["row"], 3).data(QTY_ROLE) or "0")
            if Decimal(entered) < 0 or Decimal(entered) > remaining:
                QMessageBox.warning(
                    self, tr(self.language, "error"),
                    f"{tr(self.language, 'return_qty')}: {entered} > "
                    f"{tr(self.language, 'remaining')}: {remaining}",
                )
                return
            items.append(
                {"sale_item_id": line["sale_item_id"], "quantity": entered}
            )
        if not items:
            QMessageBox.warning(
                self, tr(self.language, "error"),
                tr(self.language, "new_return"),
            )
            return
        try:
            result = return_sale(
                self.runtime.db,
                tenant_id=self._tenant_id(),
                branch_id=self._branch_id(),
                device_id=self._device_id(),
                sale_uuid=self._sale["uuid"],
                items=items,
                reason=self.reason.text().strip() or None,
                approved_by=self.user.get("uuid"),
                accounting=self.runtime.accounting,
                ledger=self.runtime.inventory,
                outbox=self.runtime.outbox,
            )
        except Exception as exc:
            QMessageBox.critical(self, tr(self.language, "error"), str(exc))
            return
        QMessageBox.information(
            self, tr(self.language, "new_return"),
            f"{tr(self.language, 'saved_locally')}"
            f" — {money_text(Decimal(result['refund_total']))}",
        )
        self._load_invoice()
