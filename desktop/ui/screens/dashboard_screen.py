"""Dashboard: real local KPIs computed with Decimal aggregation.

Works completely offline from the local database. Numbers derive from
committed local transactions; pending-synchronization counts are shown
separately so local data is never confused with cloud-confirmed data.
"""

from __future__ import annotations

from decimal import Decimal

from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ...business_logic.reports import dashboard_summary
from ..i18n import tr
from .common import money_text

KPI_KEYS = [
    "today_sales", "today_count", "month_sales", "lifetime_sales",
    "gross_profit", "expenses_total", "net_profit", "inventory_value",
    "receivables", "payables", "low_stock", "pending_sync",
    "pending_events", "sync_conflicts",
]

COUNT_KEYS = {"today_count", "low_stock", "pending_sync", "pending_events",
              "sync_conflicts"}

VALUE_KEY_BY_LABEL = {
    "today_sales": "today_sales_total",
    "today_count": "today_sales_count",
    "month_sales": "month_sales_total",
    "lifetime_sales": "lifetime_sales_total",
    "gross_profit": "gross_profit",
    "expenses_total": "expenses_total",
    "net_profit": "net_profit",
    "inventory_value": "inventory_value",
    "receivables": "receivables_total",
    "payables": "payables_total",
    "low_stock": "low_stock_count",
    "pending_sync": "pending_sync_sales",
    "pending_events": "pending_sync_events",
    "sync_conflicts": "sync_conflicts",
}


class DashboardScreen(QWidget):
    def __init__(self, runtime, language: str):
        super().__init__()
        self.runtime = runtime
        self.language = language
        layout = QVBoxLayout(self)

        grid = QGridLayout()
        self.labels: dict[str, QLabel] = {}
        for index, key in enumerate(KPI_KEYS):
            frame = QFrame()
            frame.setFrameShape(QFrame.StyledPanel)
            frame.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            inner = QVBoxLayout(frame)
            title = QLabel(f"<b>{tr(language, key)}</b>")
            value = QLabel("0")
            value.setStyleSheet("font-size: 18pt; font-weight: 600;")
            self.labels[key] = value
            inner.addWidget(title)
            inner.addWidget(value)
            grid.addWidget(frame, index // 2, index % 2)
        layout.addLayout(grid)

        buttons = QHBoxLayout()
        refresh = QPushButton(tr(language, "refresh"))
        refresh.clicked.connect(self.reload)
        buttons.addWidget(refresh)
        buttons.addStretch(1)
        layout.addLayout(buttons)
        layout.addStretch(1)
        self.reload()

    def reload(self) -> None:
        tenant = self._tenant_id()
        summary = dashboard_summary(self.runtime.db, tenant)
        for key in KPI_KEYS:
            value = summary[VALUE_KEY_BY_LABEL[key]]
            if key in COUNT_KEYS:
                self.labels[key].setText(str(int(value)))
            else:
                self.labels[key].setText(money_text(Decimal(value)) + " YER")

    def _tenant_id(self) -> str:
        if self.runtime.device:
            return self.runtime.device.get("tenant_id") or "local"
        return "local"
