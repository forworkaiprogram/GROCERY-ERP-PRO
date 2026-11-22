"""Reports screen: daily sales (local, honest Decimal math)."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QSpinBox,
)

from ...business_logic.reports import daily_sales
from ..i18n import tr
from .common import ListScreen, money_text


class ReportsScreen(ListScreen):
    def __init__(self, runtime, language: str):
        super().__init__(runtime, language)
        self._setup_table(["day", "count", "total", "profit"])
        days_row = QHBoxLayout()
        days_row.addWidget(QLabel(tr(language, "day")))
        self.days = QSpinBox()
        self.days.setRange(1, 365)
        self.days.setValue(30)
        self.days.valueChanged.connect(self.reload)
        days_row.addWidget(self.days)
        days_row.addStretch(1)
        self.layout().insertLayout(1, days_row)
        self.reload()

    def reload(self) -> None:
        tenant = self._tenant_id()
        rows = daily_sales(self.runtime.db, tenant, days=self.days.value())
        self._show_rows([
            [
                r["day"],
                str(r["count"]),
                money_text(r["total"]),
                money_text(r["profit"]),
            ]
            for r in rows
        ])
