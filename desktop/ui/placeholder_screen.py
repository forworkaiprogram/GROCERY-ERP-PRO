"""Module screens that exist in the navigation but expose local data with
read-only lists in this build phase. Each screen declares its data source
and works offline from the local database. Placeholder screens intentionally
show real local data rather than dead buttons; interactive editing screens
arrive with their implementation phases (STATUS.md tracks this openly)."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

DATA_SOURCES = {
    "dashboard": None,
    "products": ("products", ["name", "sku", "price", "status"]),
    "inventory": (
        "inventory_balances",
        ["product_uuid", "branch_id", "quantity", "reserved_qty"],
    ),
    "purchasing": ("suppliers", ["name", "phone", "balance", "payment_terms_days"]),
    "customers": ("customers", ["name", "phone", "balance", "group_name"]),
    "accounting": ("accounts", ["code", "name", "type", "is_cash"]),
    "expenses": ("expense_categories", ["name"]),
    "hr": ("app_config", ["key", "value"]),
    "reports": None,
    "sync": ("sync_logs", ["at", "level", "message"]),
    "updates": ("update_status", ["current_version", "download_state", "last_error"]),
    "subscriptions": ("entitlement_cache", ["plan", "valid_until", "verified"]),
    "settings": ("app_config", ["key", "value"]),
}


class PlaceholderScreen(QWidget):
    def __init__(self, key: str, runtime):
        super().__init__()
        self.key = key
        self.runtime = runtime
        layout = QVBoxLayout(self)
        spec = DATA_SOURCES.get(key)
        self.table = None
        self._spec_time = None
        if spec:
            table_name, columns = spec
            self.table = QTableWidget(0, len(columns))
            self.table.setHorizontalHeaderLabels(columns)
            layout.addWidget(self.table)
            self._table_name = table_name
            self._columns = columns
        self.reload()

    def reload(self):
        if self.table is None:
            return
        try:
            rows = self.runtime.db.query_all(
                f"SELECT {', '.join(self._columns)} FROM {self._table_name} LIMIT 200"
            )
        except Exception:
            return
        self.table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            for c, col in enumerate(self._columns):
                self.table.setItem(
                    r, c, QTableWidgetItem(str(row[c] if row[c] is not None else "-"))
                )
