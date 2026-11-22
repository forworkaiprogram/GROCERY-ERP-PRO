"""Stocktake screen: expected vs counted, wired to stocktake.submit_count()."""

from __future__ import annotations

from decimal import Decimal

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...business_logic.stocktake import current_balances, submit_count
from ..i18n import tr
from .common import SessionContextMixin

_COUNTED_ROLE = Qt.UserRole + 1


class StocktakeScreen(SessionContextMixin, QWidget):
    def __init__(self, runtime, language: str):
        super().__init__()
        self.runtime = runtime
        self.language = language
        self._uuids: list[str] = []

        layout = QVBoxLayout(self)
        header = QLabel(f"🧮 {tr(language, 'stocktake')}")
        header.setObjectName("pageHeader")
        layout.addWidget(header)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels([
            tr(language, "product"), tr(language, "expected_col"),
            tr(language, "counted_col"), tr(language, "remaining"),
        ])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        layout.addWidget(self.table, 4)

        actions = QHBoxLayout()
        submit = QPushButton(tr(language, "submit_stocktake"))
        submit.clicked.connect(self._submit)
        actions.addWidget(submit)
        actions.addStretch(1)
        layout.addLayout(actions)
        self.reload()

    def reload(self) -> None:
        tenant = self._tenant_id()
        rows = current_balances(self.runtime.db, tenant)
        self._uuids = []
        self.table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            self._uuids.append(row["product_uuid"])
            for c, value in enumerate([
                row["name"], row["expected"], "", row["expected"],
            ]):
                cell = QTableWidgetItem(value)
                self.table.setItem(r, c, cell)
            self.table.item(r, 0).setFlags(
                self.table.item(r, 0).flags() & ~Qt.ItemIsEditable
            )
            self.table.item(r, 1).setFlags(
                self.table.item(r, 1).flags() & ~Qt.ItemIsEditable
            )
            self.table.item(r, 3).setFlags(
                self.table.item(r, 3).flags() & ~Qt.ItemIsEditable
            )
            self.table.item(r, 3).setData(_COUNTED_ROLE, row["expected"])
        if not rows:
            self.table.setRowCount(0)

    def _submit(self) -> None:
        items = []
        for row in range(self.table.rowCount()):
            counted_cell = self.table.item(row, 2)
            if counted_cell is None:
                continue
            text = (counted_cell.text() or "").strip()
            if not text:
                continue
            expected = Decimal(self.table.item(row, 3).data(_COUNTED_ROLE) or "0")
            if Decimal(text) < 0:
                QMessageBox.warning(
                    self, tr(self.language, "error"),
                    f"{tr(self.language, 'return_qty')}: {text}",
                )
                return
            items.append({
                "product_uuid": self._uuids[row],
                "counted": text,
                "expected": str(expected),
            })
        if not items:
            QMessageBox.information(
                self, tr(self.language, "stocktake"),
                tr(self.language, "enter_all_fields"),
            )
            return
        try:
            result = submit_count(
                self.runtime.db,
                self.runtime.inventory,
                self.runtime.outbox,
                tenant_id=self._tenant_id(),
                branch_id=self._branch_id(),
                device_id=self._device_id(),
                counted_by=self._user_uuid(),
                items=items,
            )
        except Exception as exc:
            QMessageBox.critical(self, tr(self.language, "error"), str(exc))
            return
        QMessageBox.information(
            self, tr(self.language, "stocktake"),
            f"{tr(self.language, 'stocktake_done')}: "
            f"{result['adjusted']}/{result['accepted']}",
        )
        self.reload()
