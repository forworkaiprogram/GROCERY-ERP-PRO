"""Purchases screen: goods receiving wired to receive_purchase().

One local transaction per receipt: inventory movements + balanced
journal + supplier balance + purchase.received outbox event.
"""

from __future__ import annotations

from decimal import Decimal

from PySide6.QtCore import Qt
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

from ...business_logic.purchases import receive_purchase
from ..i18n import tr
from .common import ListScreen, money_text


class PurchasesScreen(ListScreen):
    def __init__(self, runtime, language: str):
        super().__init__(runtime, language)
        self._setup_table(
            ["created", "supplier", "total", "paid", "status"]
        )
        actions = QHBoxLayout()
        receive = QPushButton(tr(language, "receive_purchase"))
        receive.clicked.connect(self._open_receive_dialog)
        actions.addWidget(receive)
        actions.addStretch(1)
        self.layout().addLayout(actions)
        self.reload()

    def reload(self) -> None:
        tenant = self._tenant_id()
        rows = self.runtime.db.query_all(
            "SELECT pv.*, s.name AS supplier_name FROM purchase_vouchers pv"
            " LEFT JOIN suppliers s ON s.uuid = pv.supplier_uuid"
            " WHERE pv.tenant_id=? ORDER BY pv.created_at DESC LIMIT 300",
            (tenant,),
        )
        self._show_rows([
            [
                (r["created_at"] or "")[:19],
                r["supplier_name"] or "-",
                money_text(Decimal(r["total"])),
                money_text(Decimal(r["paid_amount"])),
                r["status"],
            ]
            for r in rows
        ])

    def _open_receive_dialog(self) -> None:
        tenant = self._tenant_id()
        suppliers = self.runtime.db.query_all(
            "SELECT uuid, name FROM suppliers WHERE tenant_id=?"
            " ORDER BY name",
            (tenant,),
        )
        products = self.runtime.db.query_all(
            "SELECT uuid, name, name_ar, cost FROM products WHERE tenant_id=?"
            " AND status='ACTIVE' ORDER BY name",
            (tenant,),
        )
        if not products:
            QMessageBox.warning(
                self, tr(self.language, "purchases"),
                tr(self.language, "no_product"),
            )
            return

        dialog = QWidget(self)
        dialog.setWindowTitle(tr(self.language, "receive_purchase"))
        dialog.setMinimumWidth(620)
        layout = QVBoxLayout(dialog)

        form = QFormLayout()
        supplier_combo = QComboBox()
        supplier_combo.addItem("—", None)
        for s in suppliers:
            supplier_combo.addItem(s["name"], s["uuid"])
        form.addRow(tr(self.language, "supplier"), supplier_combo)
        paid_edit = QLineEdit("0")
        method = QComboBox()
        method.addItems(["CASH", "BANK", "CARD", "WALLET"])
        form.addRow(tr(self.language, "paid_amount"), paid_edit)
        form.addRow(tr(self.language, "payment_method"), method)
        layout.addLayout(form)

        lines = QTableWidget(0, 4)
        lines.setHorizontalHeaderLabels([
            tr(self.language, "product"), tr(self.language, "qty"),
            tr(self.language, "unit_cost"), tr(self.language, "line_total"),
        ])
        lines.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        layout.addWidget(lines, 3)

        total_label = QLabel(f"{tr(self.language, 'purchase_total')}: 0.00")
        total_label.setStyleSheet("font-weight:bold;")
        layout.addWidget(total_label)

        def lines_data() -> list[dict]:
            data = []
            for row in range(lines.rowCount()):
                combo = lines.cellWidget(row, 0)
                qty_edit = lines.cellWidget(row, 1)
                cost_edit = lines.cellWidget(row, 2)
                uuid = combo.currentData() if combo else None
                if not uuid or qty_edit is None or cost_edit is None:
                    continue
                data.append({
                    "product_uuid": uuid,
                    "quantity": qty_edit.text() or "0",
                    "unit_cost": (cost_edit.text() or "0").replace(",", ""),
                })
            return data

        def recalc() -> None:
            try:
                total = sum(
                    (Decimal(d["quantity"]) * Decimal(d["unit_cost"])
                     for d in lines_data()),
                    Decimal("0"),
                )
                paid = Decimal(
                    (paid_edit.text() or "0").replace(",", "") or "0"
                )
            except Exception:
                return
            total_label.setText(
                f"{tr(self.language, 'purchase_total')}: "
                f"{money_text(total)} — {tr(self.language, 'credit_part')}: "
                f"{money_text(max(total - paid, Decimal('0')))}"
            )

        def add_line() -> None:
            lines.insertRow(lines.rowCount())
            r = lines.rowCount() - 1
            combo = QComboBox()
            for p in products:
                combo.addItem(p["name"] if not p["name_ar"] else p["name_ar"], p["uuid"])
            widget_button = lines.cellWidget(r, 0)
            lines.setCellWidget(r, 0, combo)
            if widget_button is None:
                lines.removeCellWidget(r, 0)
                lines.setCellWidget(r, 0, combo)
            qty_edit = QLineEdit("1")
            cost_edit = QLineEdit(str(products[0]["cost"] if products else "0"))
            lines.setCellWidget(r, 1, qty_edit)
            lines.setCellWidget(r, 2, cost_edit)
            shown = QTableWidgetItem("0.00")
            shown.setFlags(shown.flags() & ~Qt.ItemIsEditable)
            lines.setItem(r, 3, shown)

            qty_edit.textChanged.connect(recalc)
            cost_edit.textChanged.connect(recalc)
            paid_edit.textChanged.connect(recalc)

            def combo_changed(index: int) -> None:
                uuid = combo.itemData(index)
                for p in products:
                    if p["uuid"] == uuid:
                        cost_edit.setText(str(p["cost"]))
                        break
                recalc()

            combo.currentIndexChanged.connect(combo_changed)
            recalc()

        btns = QHBoxLayout()
        add_line_btn = QPushButton(tr(self.language, "add_line"))
        add_line_btn.clicked.connect(add_line)
        remove_line_btn = QPushButton(tr(self.language, "remove_line"))
        remove_line_btn.clicked.connect(
            lambda: lines.removeRow(max(lines.currentRow(), 0))
        )
        btns.addWidget(add_line_btn)
        btns.addWidget(remove_line_btn)
        btns.addStretch(1)
        save = QPushButton(tr(self.language, "save"))
        cancel = QPushButton(tr(self.language, "cancel"))
        btns.addWidget(save)
        btns.addWidget(cancel)
        layout.addLayout(btns)

        def submit() -> None:
            items = lines_data()
            if not items:
                QMessageBox.warning(
                    self, tr(self.language, "purchases"),
                    tr(self.language, "enter_all_fields"),
                )
                return
            try:
                result = receive_purchase(
                    self.runtime.db,
                    tenant_id=tenant,
                    branch_id=self._branch_id(),
                    device_id=self._device_id(),
                    supplier_uuid=supplier_combo.currentData(),
                    items=items,
                    paid_amount=paid_edit.text() or "0",
                    payment_method=method.currentText(),
                    created_by=self._user_uuid(),
                    accounting=self.runtime.accounting,
                    ledger=self.runtime.inventory,
                    outbox=self.runtime.outbox,
                )
            except Exception as exc:
                QMessageBox.critical(self, tr(self.language, "error"), str(exc))
                return
            QMessageBox.information(
                self, tr(self.language, "purchases"),
                f"{tr(self.language, 'saved_locally')} — {result['total']}",
            )
            dialog.close()
            self.reload()

        save.clicked.connect(submit)
        cancel.clicked.connect(dialog.close)
        add_line()
        dialog.refs = {
            "supplier": supplier_combo,
            "paid": paid_edit,
            "method": method,
            "lines": lines,
            "save": save,
        }
        dialog.show()
