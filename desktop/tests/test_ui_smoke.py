"""End-to-end UI smoke test (offscreen Qt).

Runs the real screen handlers exactly as user interaction would:
login -> product -> purchase -> POS sale -> return -> stocktake ->
customer payment -> shift close -> backup -> theme toggle.

Skipped automatically when PySide6 cannot initialize a QApplication
(e.g. minimal environments without Qt system libraries).
"""

import os
import uuid as uuidlib
from decimal import Decimal

import pytest


def _qt_available() -> bool:
    try:
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance() or QApplication([])
        return app is not None
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _qt_available(), reason="Qt system libraries unavailable"
)

BARCODE = "6280000000025"


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture(scope="module")
def session(qapp, tmp_path_factory):
    import PySide6.QtWidgets as QtWidgets

    for name in ("information", "warning", "critical"):
        setattr(
            QtWidgets.QMessageBox, name,
            staticmethod(lambda *a, **k: None),
        )

    tmp_path = tmp_path_factory.mktemp("erp_home")
    os.environ["GROCERY_ERP_HOME"] = str(tmp_path)
    from desktop.app.bootstrap import DesktopRuntime
    from desktop.security.local_auth import LocalAuth
    from desktop.ui.main_window import MainWindow
    from desktop.ui.theme import apply_theme

    apply_theme(qapp, "light")
    runtime = DesktopRuntime(data_dir=tmp_path)
    runtime.initialize()
    user = LocalAuth(runtime.db).login("admin", "admin123")
    window = MainWindow(runtime, language="ar", user=user)
    window.show()
    yield {"window": window, "runtime": runtime, "user": user}
    runtime.shutdown()
    os.environ.pop("GROCERY_ERP_HOME", None)


def _login_dialog_flow(session):
    runtime = session["runtime"]
    from desktop.ui.login_dialog import LoginDialog

    dialog = LoginDialog(runtime, language="ar")
    dialog.username.setText("admin")
    dialog.password.setText("wrong")
    dialog._login()
    assert dialog.user is None and not dialog.result() == 1
    dialog2 = LoginDialog(runtime, language="ar")
    dialog2.username.setText("admin")
    dialog2.password.setText("admin123")
    dialog2._login()
    assert dialog2.user is not None and dialog2.user["role"] == "admin"


def _create_product(session):
    window = session["window"]
    screen = window._screens["products"]
    screen._create_product(
        {
            "name": "Milk 1L",
            "name_ar": "حليب 1 لتر",
            "sku": f"MILK-{uuidlib.uuid4().hex[:6]}",
            "barcode": BARCODE,
            "cost": "500",
            "price": "1000",
            "tax_percent": "0",
            "min_stock": "10",
        }
    )
    assert screen.table.rowCount() >= 1


def _receive_purchase(session):
    window = session["window"]
    runtime = session["runtime"]
    tenant = window._screens["products"]._tenant_id()

    with runtime.db.transaction() as tx:
        tx.execute(
            "INSERT OR IGNORE INTO suppliers (uuid, tenant_id, name, credit_limit,"
            " payment_terms_days) VALUES (?,?,?,0,0)",
            ("sup-" + uuidlib.uuid4().hex[:8], tenant, "مورد الحليب"),
        )
    screen = window._screens["purchases"]
    screen._open_receive_dialog()
    import PySide6.QtWidgets as QtWidgets

    dialog = None
    for child in screen.findChildren(QtWidgets.QWidget):
        refs = getattr(child, "refs", None)
        if refs:
            dialog = child
            break
    assert dialog is not None, "receive dialog was not opened"
    refs = dialog.refs
    refs["supplier"].setCurrentIndex(1)
    rows = runtime.db.query_all(
        "SELECT uuid FROM products WHERE tenant_id=?", (tenant,)
    )
    lines = refs["lines"]
    refs["paid"].setText("0")
    qty_edit = lines.cellWidget(0, 1)
    cost_edit = lines.cellWidget(0, 2)
    qty_edit.setText("20")
    cost_edit.setText("500")
    combo = lines.cellWidget(0, 0)
    combo.setCurrentIndex(combo.findData(rows[0]["uuid"]))
    refs["save"].click()
    voucher = runtime.db.query_one(
        "SELECT * FROM purchase_vouchers ORDER BY created_at DESC LIMIT 1"
    )
    assert voucher is not None
    assert Decimal(voucher["total"]) == Decimal("10000")
    product_uuid = rows[0]["uuid"]
    balance = runtime.db.query_one(
        "SELECT quantity FROM inventory_balances WHERE product_uuid=?",
        (product_uuid,),
    )
    assert Decimal(balance["quantity"]) == Decimal("20")


def _commit_pos_sale(session):
    window = session["window"]
    runtime = session["runtime"]
    screen = window._screens["pos"]
    screen.reload()
    screen.search.setText(BARCODE)
    screen._on_scan()
    assert screen.table.rowCount() == 1
    screen._on_commit()
    balance = runtime.db.query_one(
        "SELECT quantity FROM inventory_balances"
    )["quantity"]
    assert Decimal(balance) == Decimal("19")
    events = [
        e["event_type"] for e in runtime.db.query_all(
            "SELECT event_type FROM outbox_events"
        )
    ]
    assert "sale.created" in events


def _return_items(session):
    window = session["window"]
    runtime = session["runtime"]
    from PySide6.QtCore import Qt

    sale = runtime.db.query_one("SELECT * FROM sales ORDER BY created_at DESC LIMIT 1")
    screen = window._screens["returns"]
    screen.search.setText(sale["invoice_no"])
    screen._load_invoice()
    assert screen.table.rowCount() == 1
    remaining = Decimal(screen.table.item(0, 3).data(Qt.UserRole + 1))
    assert remaining == Decimal("1")
    screen.table.item(0, 4).setText("1")
    screen._submit()
    sale_after = runtime.db.query_one(
        "SELECT status FROM sales WHERE uuid=?", (sale["uuid"],)
    )
    assert sale_after["status"] in ("RETURNED", "PARTIALLY_RETURNED")
    balance = runtime.db.query_one(
        "SELECT quantity FROM inventory_balances"
    )["quantity"]
    assert Decimal(balance) == Decimal("20")
    events = [
        e["event_type"] for e in runtime.db.query_all(
            "SELECT event_type FROM outbox_events"
        )
    ]
    assert "sale.returned" in events


def _stocktake(session):
    window = session["window"]
    runtime = session["runtime"]
    screen = window._screens["stocktake"]
    screen.reload()
    assert screen.table.rowCount() >= 1
    screen.table.item(0, 2).setText("17")
    screen._submit()
    balance = runtime.db.query_one(
        "SELECT quantity FROM inventory_balances"
    )["quantity"]
    assert Decimal(balance) == Decimal("17")


def _customer_debt_then_payment(session):
    window = session["window"]
    runtime = session["runtime"]
    tenant = window._screens["products"]._tenant_id()
    cust_uuid = "cus-" + uuidlib.uuid4().hex[:8]
    with runtime.db.transaction() as tx:
        tx.execute(
            "INSERT INTO customers (uuid, tenant_id, name, credit_limit,"
            " balance, discount_bps) VALUES (?,?,?,50000,5000,0)",
            (cust_uuid, tenant, "عميل بالدين"),
        )
    screen = window._screens["debts"]
    window._navigate("debts")
    screen.reload()
    assert screen.table.rowCount() >= 1
    row = screen._debt_order.index(cust_uuid)
    screen.table.setCurrentCell(row, 0)
    screen._open_payment_dialog()
    import PySide6.QtWidgets as QtWidgets
    from PySide6.QtWidgets import QLineEdit

    # locate: the dialog is the visible child with form editors
    candidates = []
    for child in screen.findChildren(QtWidgets.QWidget):
        if child.parent() is not screen:
            continue
        edits = child.findChildren(QLineEdit)
        combos = child.findChildren(QtWidgets.QComboBox)
        buttons = child.findChildren(QtWidgets.QPushButton)
        if edits and combos and len(buttons) >= 2:
            candidates.append((child, edits, combos, buttons))
    assert candidates, "payment dialog not found"
    dialog, edits, combos, buttons = candidates[-1]
    edits[0].setText("2000")
    _save = None
    for btn in buttons:
        if btn.text() in ("حفظ", "Save"):
            _save = btn
    _save.click()
    balance = runtime.db.query_one(
        "SELECT balance FROM customers WHERE uuid=?", (cust_uuid,)
    )["balance"]
    assert Decimal(balance) == Decimal("3000")


def _shift_flow(session):
    window = session["window"]
    runtime = session["runtime"]
    screen = window._screens["shifts"]
    screen.reload()
    screen.opening_edit.setText("1000")
    screen._open()
    open_session = runtime.db.query_one(
        "SELECT * FROM cash_sessions WHERE status='OPEN'"
    )
    assert open_session is not None
    screen.reload()
    screen.counted_edit.setText("12000")
    screen._close()
    closed = runtime.db.query_one(
        "SELECT * FROM cash_sessions WHERE uuid=?", (open_session["uuid"],)
    )
    assert closed["status"] == "CLOSED"
    assert closed["expected_balance"] is not None


def _backup_flow(session):
    runtime = session["runtime"]
    path = runtime.backup.create(label="smoke")
    assert runtime.backup.verify(path)
    assert path.exists()


def _theme_toggle(session):
    window = session["window"]
    from desktop.ui.theme import configured_theme

    before = configured_theme(session["runtime"].db)
    window._toggle_theme()
    after = configured_theme(session["runtime"].db)
    assert {before, after} == {"light", "dark"}


def test_full_business_flow(qapp, session):
    _login_dialog_flow(session)
    _create_product(session)
    _receive_purchase(session)
    _commit_pos_sale(session)
    _return_items(session)
    _stocktake(session)
    _customer_debt_then_payment(session)
    _shift_flow(session)
    _backup_flow(session)
    _theme_toggle(session)


def test_dashboard_and_navigation(qapp, session):
    window = session["window"]
    window._navigate("dashboard")
    label = window._screens["dashboard"].labels["today_sales"]
    assert label.text() not in {"0", "0.00 YER", "0.00"}
    for key in window._nav_order:
        window._navigate(key)
