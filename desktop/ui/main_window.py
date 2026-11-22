"""Main application window: navigation + module screens.

Modules map to real PySide6 screens wired to DesktopRuntime services
(local-first; every screen works offline). The window keeps business
logic OUT of UI classes.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QStackedWidget,
    QStatusBar,
    QWidget,
)

from .i18n import tr
from .screens import (
    AccountingScreen,
    CustomersScreen,
    DashboardScreen,
    ExpensesScreen,
    InventoryScreen,
    NoticeScreen,
    ProductsScreen,
    ReportsScreen,
    SuppliersScreen,
    TableScreen,
)


MODULES = [
    ("dashboard", None),
    ("pos", None),
    ("products", None),
    ("inventory", None),
    ("purchasing", None),
    ("customers", None),
    ("accounting", None),
    ("expenses", None),
    ("hr", None),
    ("reports", None),
    ("sync", ("sync_logs", ["at", "level", "message"])),
    ("updates", ("update_status", ["current_version", "download_state", "last_error"])),
    ("subscriptions", ("entitlement_cache", ["plan", "valid_until", "verified"])),
    ("settings", ("app_config", ["key", "value"])),
]


class MainWindow(QMainWindow):
    def __init__(self, runtime, language: str = "ar"):
        super().__init__()
        self.runtime = runtime
        self.language = language
        self.setWindowTitle(tr(language, "app_title"))
        self.resize(1280, 800)
        self.setLayoutDirection(
            Qt.RightToLeft if language == "ar" else Qt.LeftToRight
        )

        self._nav = QListWidget()
        for key, _spec in MODULES:
            QListWidgetItem(tr(language, key), self._nav)
        self._stack = QStackedWidget()

        from .pos.pos_screen import PosScreen

        self._screens = {
            "dashboard": DashboardScreen(runtime, language),
            "pos": PosScreen(runtime),
            "products": ProductsScreen(runtime, language),
            "inventory": InventoryScreen(runtime, language),
            "purchasing": SuppliersScreen(runtime, language),
            "customers": CustomersScreen(runtime, language),
            "accounting": AccountingScreen(runtime, language),
            "expenses": ExpensesScreen(runtime, language),
            "hr": NoticeScreen(runtime, language, "hr_notice"),
            "reports": ReportsScreen(runtime, language),
        }
        for key, spec in MODULES:
            if key not in self._screens:
                table, columns = spec
                self._screens[key] = TableScreen(runtime, language, table, columns)
        for widget in self._screens.values():
            self._stack.addWidget(widget)

        central = QWidget()
        layout = QHBoxLayout(central)
        layout.addWidget(self._nav, 1)
        layout.addWidget(self._stack, 4)
        self.setCentralWidget(central)
        self._nav.currentRowChanged.connect(self._on_navigate)
        self._nav.setCurrentRow(0)
        self._on_navigate(0)

        status = QStatusBar()
        self.setStatusBar(status)
        self._sync_label = QLabel()
        status.addPermanentWidget(self._sync_label)

    def set_sync_state(self, online: bool, pending: int,
                       acknowledged_at: str | None) -> None:
        mode = (tr(self.language, "sync") + ": "
                + ("ONLINE" if online else "OFFLINE"))
        self._sync_label.setText(
            f"{mode} | pending: {pending} | last ack: {acknowledged_at or '-'}"
        )

    def _on_navigate(self, index: int) -> None:
        key = MODULES[index][0]
        widget = self._screens[key]
        reload_method = getattr(widget, "reload", None)
        if callable(reload_method):
            try:
                reload_method()
            except Exception:
                logging.exception("screen %s failed to reload", key)
        self._stack.setCurrentWidget(widget)
