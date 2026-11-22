"""Main application window: navigation + module screens.

Modules map to permission flags from the cached entitlement/auth context.
The window keeps all business logic OUT of UI classes — screens call
DesktopRuntime services only.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QStackedWidget,
    QStatusBar,
    QToolBar,
    QWidget,
)

MODULES = [
    ("dashboard", "Dashboard", "dashboard", "(all)"),
    ("pos", "Point of Sale", "pos", "(all)"),
    ("products", "Products", "products", "(all)"),
    ("inventory", "Inventory", "inventory", "(all)"),
    ("purchasing", "Purchasing", "inventory", "(all)"),
    ("customers", "Customers", "products", "(all)"),
    ("accounting", "Accounting", "accounting", "(all)"),
    ("expenses", "Expenses", "inventory", "(all)"),
    ("hr", "Human Resources", "hr", "(all)"),
    ("reports", "Reports", "advanced_reports", "professional+"),
    ("sync", "Synchronization", "sync", "(all)"),
    ("updates", "Update Center", "sync", "(all)"),
    ("subscriptions", "Subscription", "sync", "(all)"),
    ("settings", "Settings", "sync", "(all)"),
]


class MainWindow(QMainWindow):
    def __init__(self, runtime, language: str = "ar"):
        super().__init__()
        self.runtime = runtime
        self.language = language
        self.setWindowTitle("GROCERY ERP PRO")
        self.resize(1280, 800)
        self.setLayoutDirection(
            Qt.RightToLeft if language == "ar" else Qt.LeftToRight
        )

        self._nav = QListWidget()
        for key, label, _flag, _tier in MODULES:
            QListWidgetItem(label, self._nav)
        self._stack = QStackedWidget()

        from .pos.pos_screen import PosScreen  # nearby-module import kept local

        self._screens = {
            "pos": PosScreen(runtime),
        }
        for index in range(self._nav.count()):
            key = MODULES[index][0]
            if key != "pos":
                from .placeholder_screen import PlaceholderScreen

                self._screens[key] = PlaceholderScreen(key, runtime)
            self._stack.addWidget(self._screens[key])

        central = QWidget()
        layout = QHBoxLayout(central)
        layout.addWidget(self._nav, 1)
        layout.addWidget(self._stack, 4)
        self.setCentralWidget(central)
        self._nav.currentRowChanged.connect(self._on_navigate)
        self._nav.setCurrentRow(1)

        status = QStatusBar()
        self.setStatusBar(status)
        self._sync_label = QLabel()
        status.addPermanentWidget(self._sync_label)

    def set_sync_state(self, online: bool, pending: int, acknowledged_at: str | None) -> None:
        mode = "ONLINE" if online else "OFFLINE (saving locally)"
        self._sync_label.setText(f"{mode} | pending: {pending} | last ack: {acknowledged_at or '-'}")

    def _on_navigate(self, index: int) -> None:
        key = MODULES[index][0]
        self._stack.setCurrentWidget(self._screens[key])
