"""Business screens wired to DesktopRuntime services."""

from .accounting_screen import AccountingScreen
from .customers_screen import CustomersScreen
from .dashboard_screen import DashboardScreen
from .debts_screen import DebtsScreen
from .expenses_screen import ExpensesScreen
from .inventory_screen import InventoryScreen
from .products_screen import ProductsScreen
from .purchases_screen import PurchasesScreen
from .reports_screen import ReportsScreen
from .returns_screen import ReturnsScreen
from .sales_screen import SalesScreen
from .settings_screen import SettingsScreen
from .shifts_screen import ShiftsScreen
from .stocktake_screen import StocktakeScreen
from .suppliers_screen import SuppliersScreen
from .tables_screen import NoticeScreen, TableScreen
from .users_screen import UsersScreen

__all__ = [
    "AccountingScreen",
    "CustomersScreen",
    "DashboardScreen",
    "DebtsScreen",
    "ExpensesScreen",
    "InventoryScreen",
    "NoticeScreen",
    "ProductsScreen",
    "PurchasesScreen",
    "ReportsScreen",
    "ReturnsScreen",
    "SalesScreen",
    "SettingsScreen",
    "ShiftsScreen",
    "StocktakeScreen",
    "SuppliersScreen",
    "TableScreen",
    "UsersScreen",
]
