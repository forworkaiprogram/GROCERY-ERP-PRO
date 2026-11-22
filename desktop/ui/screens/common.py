"""Shared building blocks for module screens (Arabic-first RTL)."""

from __future__ import annotations

import uuid as uuidlib

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
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


def money_text(value) -> str:
    return f"{value:,.2f}"


def qty_text(value) -> str:
    text = f"{value:,.4f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


class FormDialog(QWidget):
    def __init__(self, parent, runtime, language, title_key, fields: dict, on_submit):
        super().__init__(parent)
        self.runtime = runtime
        self.language = language
        self.on_submit = on_submit
        self.setWindowTitle(tr(language, title_key))
        self.setMinimumWidth(420)

        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.inputs: dict[str, QLineEdit] = {}
        for key, label_key in fields.items():
            editor = QLineEdit()
            self.inputs[key] = editor
            form.addRow(tr(language, label_key), editor)
        layout.addLayout(form)

        buttons = QHBoxLayout()
        save = QPushButton(tr(language, "save"))
        save.clicked.connect(self._submit)
        cancel = QPushButton(tr(language, "cancel"))
        cancel.clicked.connect(self.close)
        buttons.addWidget(save)
        buttons.addWidget(cancel)
        layout.addLayout(buttons)

    def _submit(self) -> None:
        values = {key: edit.text().strip() for key, edit in self.inputs.items()}
        try:
            self.on_submit(values)
        except Exception as exc:
            QMessageBox.critical(
                self, tr(self.language, "error"),
                f"{type(exc).__name__}: {exc}",
            )
            return
        QMessageBox.information(
            self, tr(self.language, "app_title"), tr(self.language, "saved")
        )
        self.close()


class ListScreen(QWidget):
    """Toolbar + table grid base; subclasses supply queries and actions."""

    def __init__(self, runtime, language: str):
        super().__init__()
        self.runtime = runtime
        self.language = language
        self.columns: list[str] = []

        layout = QVBoxLayout(self)
        toolbar = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText(tr(language, "search"))
        self.search.textChanged.connect(self.reload)
        refresh = QPushButton(tr(language, "refresh"))
        refresh.clicked.connect(self.reload)
        toolbar.addWidget(self.search, 3)
        toolbar.addWidget(refresh)
        layout.addLayout(toolbar)

        self.table = QTableWidget(0, 0)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        layout.addWidget(self.table, 4)

    def _tenant_id(self) -> str:
        if self.runtime.device:
            return self.runtime.device.get("tenant_id") or "local"
        return "local"

    def _setup_table(self, columns: list[str]) -> None:
        self.columns = [tr(self.language, c) for c in columns]
        self.table.setColumnCount(len(self.columns))
        self.table.setHorizontalHeaderLabels(self.columns)
        self._column_keys = columns

    def _show_rows(self, rows: list[list[str]]) -> None:
        self.table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            for c, value in enumerate(row):
                item = QTableWidgetItem(str(value))
                item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.table.setItem(r, c, item)

    def reload(self) -> None:
        raise NotImplementedError
