"""Main application shell: sidebar navigation + stacked pages.

Arabic-first RTL shell modeled on the reference Smart Grocery ERP but
wired to the tested engines (local-first, Decimal, outbox). RBAC comes
from the local auth session. Business logic stays OUT of these classes
— pages delegate to DesktopRuntime services.
"""

from __future__ import annotations

import logging
from datetime import datetime

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QStackedWidget,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from .i18n import tr
from .pos.pos_screen import PosScreen
from .screens import (
    AccountingScreen,
    CustomersScreen,
    DashboardScreen,
    ExpensesScreen,
    NoticeScreen,
    ProductsScreen,
    ReportsScreen,
    SuppliersScreen,
    TableScreen,
)
from .screens.debts_screen import DebtsScreen
from .screens.purchases_screen import PurchasesScreen
from .screens.returns_screen import ReturnsScreen
from .screens.sales_screen import SalesScreen
from .screens.settings_screen import SettingsScreen
from .screens.shifts_screen import ShiftsScreen
from .screens.stocktake_screen import StocktakeScreen
from .screens.users_screen import UsersScreen

EMOJI = {
    "dashboard": "🏠", "products": "📦", "pos": "🛒", "sales": "🧾",
    "purchases": "📥", "returns": "↩", "customers": "👥",
    "suppliers": "🚚", "debts": "💰", "stocktake": "🧮",
    "shifts": "📋", "users": "👤", "accounting": "📚",
    "expenses": "💸", "reports": "📊", "sync": "🔄",
    "updates": "⬆", "subscriptions": "💠", "settings": "⚙",
    "hr": "🗂",
}

RBAC = {
    "admin": [
        "dashboard", "products", "pos", "sales", "purchases", "returns",
        "customers", "suppliers", "debts", "stocktake", "shifts", "users",
        "accounting", "expenses", "reports", "sync", "updates",
        "subscriptions", "settings",
    ],
    "manager": [
        "dashboard", "products", "pos", "sales", "purchases", "returns",
        "customers", "suppliers", "debts", "stocktake", "shifts",
        "accounting", "expenses", "reports", "sync", "settings",
    ],
    "cashier": [
        "dashboard", "pos", "sales", "customers", "debts", "shifts", "sync",
    ],
    "accountant": [
        "dashboard", "sales", "returns", "customers", "suppliers", "debts",
        "purchases", "accounting", "expenses", "reports",
    ],
}


class MainWindow(QMainWindow):
    def __init__(self, runtime, language: str = "ar", user: dict | None = None):
        super().__init__()
        self.runtime = runtime
        self.language = language
        self.user = user or {"username": "local", "name": "local",
                             "role": "admin", "uuid": None}
        store_name = (
            runtime.db.query_one(
                "SELECT value FROM app_config WHERE key='store_name'"
            )
        )
        store_name = store_name["value"] if store_name else "GROCERY ERP PRO"
        self.setWindowTitle(f"🏪 {tr(language, 'app_title')} — {store_name}")
        self.resize(1180, 720)
        if language == "ar":
            self.setLayoutDirection(Qt.RightToLeft)

        self._screens: dict[str, QWidget] = {}
        self._builders = {
            "dashboard": lambda: DashboardScreen(runtime, language),
            "products": lambda: ProductsScreen(runtime, language),
            "pos": lambda: PosScreen(runtime, language, user=self.user),
            "sales": lambda: SalesScreen(runtime, language),
            "purchases": lambda: PurchasesScreen(runtime, language),
            "returns": lambda: ReturnsScreen(runtime, language, user=self.user),
            "customers": lambda: CustomersScreen(runtime, language),
            "suppliers": lambda: SuppliersScreen(runtime, language),
            "debts": lambda: DebtsScreen(runtime, language),
            "stocktake": lambda: StocktakeScreen(runtime, language),
            "shifts": lambda: ShiftsScreen(runtime, language),
            "users": lambda: UsersScreen(runtime, language, user=self.user),
            "accounting": lambda: AccountingScreen(runtime, language),
            "expenses": lambda: ExpensesScreen(runtime, language),
            "reports": lambda: ReportsScreen(runtime, language),
            "hr": lambda: NoticeScreen(runtime, language, "hr_notice"),
            "sync": lambda: TableScreen(
                runtime, language, "sync_logs", ["at", "level", "message"],
                title_key="sync",
            ),
            "updates": lambda: TableScreen(
                runtime, language, "update_status",
                ["current_version", "download_state", "last_error"],
                title_key="updates",
            ),
            "subscriptions": lambda: TableScreen(
                runtime, language, "entitlement_cache",
                ["plan", "valid_until", "verified"], title_key="subscriptions",
            ),
            "settings": lambda: SettingsScreen(runtime, language, user=self.user),
        }
        self._allowed = RBAC.get(self.user.get("role", "admin"), RBAC["cashier"])
        # First screen: cashier lands on POS, others on the dashboard.
        visible = [k for k in self._builders if k in self._allowed]
        self._nav_order = [k for k in (
            "dashboard", "pos", "products", "sales", "returns", "purchases",
            "customers", "suppliers", "debts", "stocktake", "shifts",
            "accounting", "expenses", "reports", "users", "hr", "sync",
            "updates", "subscriptions", "settings",
        ) if k in visible]

        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.sidebar = QWidget()
        self.sidebar.setObjectName("sidebar")
        self.sidebar.setFixedWidth(230)
        side = QVBoxLayout(self.sidebar)
        side.setContentsMargins(8, 14, 8, 10)
        side.setSpacing(4)
        logo = QLabel(f"🏪 {tr(language, 'app_title')}")
        logo.setObjectName("brandLabel")
        side.addWidget(logo)
        side.addSpacing(10)

        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        self.nav_buttons: dict[str, QWidget] = {}
        from PySide6.QtWidgets import QPushButton

        for key in self._nav_order:
            btn = QPushButton(f"{EMOJI.get(key, '•')}  {tr(language, key)}")
            btn.setObjectName("navBtn")
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(self._make_navigation(key))
            self.nav_group.addButton(btn)
            self.nav_buttons[key] = btn
            side.addWidget(btn)
        side.addStretch(1)

        self.theme_btn = QPushButton(self._theme_label())
        self.theme_btn.setObjectName("ghostBtn")
        self.theme_btn.clicked.connect(self._toggle_theme)
        side.addWidget(self.theme_btn)
        logout = QPushButton(f"🚪 {tr(language, 'logout')}")
        logout.setObjectName("logoutBtn")
        logout.clicked.connect(self._logout)
        side.addWidget(logout)
        root.addWidget(self.sidebar)

        self.stack = QStackedWidget()
        root.addWidget(self.stack, 1)

        for key in self._nav_order:
            page = self._builders[key]()
            self._screens[key] = page
            self.stack.addWidget(page)

        self._build_statusbar()
        QShortcut(QKeySequence("Ctrl+K"), self, activated=self._open_palette)

        first = "pos" if self.user.get("role") == "cashier" and "pos" in visible \
            else ("dashboard" if "dashboard" in visible else visible[0])
        self._navigate(first)

    # ---- navigation --------------------------------------------------------
    def _make_navigation(self, key: str):
        def navigate():
            self._navigate(key)
        return navigate

    def _navigate(self, key: str) -> None:
        if key not in self._screens:
            if hasattr(self, "stack"):
                import contextlib

                with contextlib.suppress(Exception):
                    self.statusBar().showMessage(
                        tr(self.language, "admin_only"), 4000
                    )
            return
        page = self._screens[key]
        if hasattr(page, "reload"):
            try:
                page.reload()
            except Exception:
                logging.exception("screen %s reload failed", key)
        self.stack.setCurrentWidget(page)
        btn = self.nav_buttons.get(key)
        if btn is not None:
            btn.setChecked(True)

    def _on_navigate(self, index: int) -> None:
        """Compatibility with index-based navigation (tests/tools)."""
        if 0 <= index < len(self._nav_order):
            self._navigate(self._nav_order[index])

    def _build_statusbar(self) -> None:
        bar = QStatusBar()
        bar.setObjectName("statusbar")
        self.setStatusBar(bar)
        self.user_label = QLabel(
            f"👤 {self.user.get('name') or self.user.get('username', '')}"
            f" ({tr(self.language, 'role')}: {self.user.get('role', '')})"
        )
        bar.addWidget(self.user_label)
        self.sync_label = QLabel(tr(self.language, "offline"))
        bar.addPermanentWidget(self.sync_label)
        self.clock_label = QLabel("")
        bar.addPermanentWidget(self.clock_label)
        self._clock = QTimer(self)
        self._clock.timeout.connect(self._tick_clock)
        self._clock.start(1000)
        self._tick_clock()

    def _tick_clock(self) -> None:
        self.clock_label.setText(datetime.now().strftime("%Y-%m-%d %H:%M"))

    # ---- shell actions -----------------------------------------------------
    def _default_admin_password_still_active(self) -> bool:
        try:
            from ..security.local_auth import _hash_password

            row = self.runtime.db.query_one(
                "SELECT password_hash, salt FROM local_users WHERE username='admin'"
            )
            if not row:
                return False
            return _hash_password("admin123", row["salt"]) == row["password_hash"]
        except Exception:
            return False

    def _theme_label(self) -> str:
        return (
            f"🌗 {tr(self.language, 'night_mode')}"
            if self._theme() == "light" else f"☀ {tr(self.language, 'day_mode')}"
        )

    def _theme(self) -> str:
        from .theme import configured_theme

        return configured_theme(self.runtime.db)

    def _toggle_theme(self) -> None:
        new_theme = "dark" if self._theme() == "light" else "light"
        self.runtime.db.execute(
            "INSERT INTO app_config (key, value) VALUES ('theme', ?)"
            " ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (new_theme,),
        )
        from .theme import apply_theme

        apply_theme(self._current_app(), new_theme)
        self.theme_btn.setText(self._theme_label())

    @staticmethod
    def _current_app():
        from PySide6.QtWidgets import QApplication

        return QApplication.instance()

    def _logout(self) -> None:
        from .login_dialog import LoginDialog

        dialog = LoginDialog(self.runtime, self.language)
        if dialog.exec() == QDialog.Accepted and dialog.user:
            self.user = dialog.user
            self.user_label.setText(
                f"👤 {self.user.get('name')} ({tr(self.language, 'role')}:"
                f" {self.user.get('role')})"
            )
            for key in ("pos", "returns", "users", "settings"):
                self._screens.pop(key, None)

    def _open_palette(self) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle(tr(self.language, "command_palette"))
        dialog.setMinimumWidth(360)
        layout = QVBoxLayout(dialog)
        search = QLineEdit()
        search.setPlaceholderText(tr(self.language, "search"))
        listing = QListWidget()
        layout.addWidget(search)
        layout.addWidget(listing)

        for key in self._nav_order:
            item = QListWidgetItem(
                f"{EMOJI.get(key, '•')}  {tr(self.language, key)}"
            )
            item.setData(Qt.UserRole, key)
            listing.addItem(item)

        def _filter(text: str) -> None:
            needle = text.strip().lower()
            for row in range(listing.count()):
                item = listing.item(row)
                key = item.data(Qt.UserRole)
                match = needle in key or needle in item.text().lower()
                listing.setRowHidden(row, bool(needle) and not match)

        def _pick(item: QListWidgetItem) -> None:
            self._navigate(item.data(Qt.UserRole))
            dialog.accept()

        search.textChanged.connect(_filter)
        listing.itemClicked.connect(_pick)
        search.textChanged.emit("")
        search.setFocus()
        dialog.exec()
