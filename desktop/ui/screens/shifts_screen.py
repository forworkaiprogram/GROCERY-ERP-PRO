"""Cash shifts (ورديات): open/close sessions with Decimal cash summary."""

from __future__ import annotations

from decimal import Decimal

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFormLayout,
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
from .common import SessionContextMixin
from .common import money_text

SHOW_KEYS = [
    ("opening", "opening_balance"),
    ("cash_in", "cash_in"),
    ("cash_out", "cash_out"),
    ("expected", "expected_cash"),
]


class ShiftsScreen(SessionContextMixin, QWidget):
    def __init__(self, runtime, language: str, user: dict | None = None):
        super().__init__()
        self.runtime = runtime
        self.language = language
        self.user = user or {}
        self._service = getattr(runtime, "sessions", None)
        if self._service is None:
            from ...business_logic.cash_sessions import CashSessionService

            self._service = CashSessionService(runtime.db)

        layout = QVBoxLayout(self)
        header = QLabel(f"📋 {tr(language, 'shifts')}")
        header.setObjectName("pageHeader")
        layout.addWidget(header)

        card = QLabel("")
        card.setObjectName("card")
        card.setWordWrap(True)
        self.summary_card = card
        layout.addWidget(card)

        opening_form = QFormLayout()
        self.opening_edit = QLineEdit("0")
        opening_form.addRow(tr(language, "opening_balance"), self.opening_edit)
        layout.addLayout(opening_form)

        open_btn = QPushButton(tr(language, "open_shift"))
        open_btn.clicked.connect(self._open)
        layout.addWidget(open_btn)

        counted_form = QFormLayout()
        self.counted_edit = QLineEdit("0")
        counted_form.addRow(tr(language, "counted_cash"), self.counted_edit)
        layout.addLayout(counted_form)

        close_btn = QPushButton(tr(language, "close_shift"))
        close_btn.clicked.connect(self._close)
        layout.addWidget(close_btn)

        layout.addWidget(QLabel(tr(language, "sessions")))
        self.history = QTableWidget(0, 7)
        self.history.setHorizontalHeaderLabels([
            tr(language, "date"), tr(language, "opening_balance"),
            tr(language, "expected_cash"), tr(language, "counted_cash"),
            tr(language, "discrepancy"), tr(language, "status"),
            tr(language, "created"),
        ])
        layout.addWidget(self.history, 3)
        self.reload()

    def _open(self) -> None:
        try:
            self._service.open_session(
                tenant_id=self._tenant_id(),
                branch_id=self._branch_id(),
                device_id=self._device_id(),
                cashier_id=self._user_uuid() or "local",
                opening_balance=self.opening_edit.text() or "0",
            )
        except Exception as exc:
            QMessageBox.critical(self, tr(self.language, "error"), str(exc))
            return
        self.reload()

    def _close(self) -> None:
        session = self._service.current_open(self._device_id())
        if session is None:
            QMessageBox.information(
                self, tr(self.language, "shifts"),
                tr(self.language, "no_shift"),
            )
            return
        try:
            result = self._service.close_session(
                session_uuid=session["uuid"],
                closing_balance=self.counted_edit.text() or "0",
            )
        except Exception as exc:
            QMessageBox.critical(self, tr(self.language, "error"), str(exc))
            return
        QMessageBox.information(
            self, tr(self.language, "shifts"),
            f"{tr(self.language, 'discrepancy')}: {money_text(
                Decimal(result['discrepancy']))}",
        )
        self.reload()

    def reload(self) -> None:
        session = self._service.current_open(self._device_id())
        lines: list[str] = []
        if session is None:
            lines.append(f"📋 {tr(self.language, 'no_shift')}")
        else:
            summary = self._service.cash_summary(session)
            for key, label in SHOW_KEYS:
                lines.append(
                    f"{tr(self.language, label)}: {money_text(summary[key])}"
                )
        self.summary_card.setText("\n".join(lines))

        rows = self.runtime.db.query_all(
            "SELECT * FROM cash_sessions WHERE device_id=?"
            " ORDER BY opened_at DESC LIMIT 50",
            (self._device_id(),),
        )
        self.history.setRowCount(len(rows))
        for r, row in enumerate(rows):
            values = [
                (row["opened_at"] or "")[:19],
                row["opening_balance"],
                row["expected_balance"] or "-",
                row["closing_balance"] or "-",
                row["discrepancy"] or "-",
                row["status"],
                (row["closed_at"] or "-")[:19],
            ]
            for c, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                self.history.setItem(r, c, item)
