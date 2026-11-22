"""Generic read-only local-data viewer (sync/updates/subscriptions/settings)
and an honest placeholder notice (HR, planned phase)."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QLabel,
    QVBoxLayout,
    QWidget,
)

from ..i18n import tr
from .common import ListScreen


class TableScreen(ListScreen):
    """Read-only view of a real local table; works offline."""

    def __init__(self, runtime, language: str, table: str,
                 columns: list[str], title_key: str | None = None):
        super().__init__(runtime, language)
        self._table = table
        self._source_columns = columns
        self._setup_table(columns)
        note = QLabel(tr(language, "read_only_note"))
        note.setWordWrap(True)
        self.layout().addWidget(note)
        self.reload()

    def reload(self) -> None:
        term = self.search.text().strip()
        like = f"%{term}%"
        where = ""
        params: tuple = ()
        if term and len(self._source_columns) >= 1:
            first = self._source_columns[0]
            where = f" WHERE {first} LIKE ?"
            params = (like,)
        columns_sql = ", ".join(self._source_columns)
        try:
            rows = self.runtime.db.query_all(
                f"SELECT {columns_sql} FROM {self._table}{where} LIMIT 300",
                params,
            )
        except Exception as exc:
            self._show_rows([[f"{type(exc).__name__}: {exc}"]])
            return
        self._show_rows([
            [str(r[c]) if r[c] is not None else "-" for c in self._source_columns]
            for r in rows
        ])


class NoticeScreen(QWidget):
    """Honest notice that the module is scheduled for a later phase."""

    def __init__(self, runtime, language: str, note_key: str):
        super().__init__()
        layout = QVBoxLayout(self)
        label = QLabel(tr(language, note_key))
        label.setWordWrap(True)
        layout.addWidget(label)
        layout.addStretch(1)
