"""Business screens wired to DesktopRuntime services."""

from .accounting_screen import AccountingScreen
from .customers_screen import CustomersScreen
from .dashboard_screen import DashboardScreen
from .expenses_screen import ExpensesScreen
from .inventory_screen import InventoryScreen
from .products_screen import ProductsScreen
from .reports_screen import ReportsScreen
from .suppliers_screen import SuppliersScreen
from .tables_screen import NoticeScreen, TableScreen

__all__ = [
    "AccountingScreen",
    "CustomersScreen",
    "DashboardScreen",
    "ExpensesScreen",
    "InventoryScreen",
    "NoticeScreen",
    "ProductsScreen",
    "ReportsScreen",
    "SuppliersScreen",
    "TableScreen",
]
