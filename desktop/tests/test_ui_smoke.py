"""End-to-end UI smoke test (offscreen Qt).

Runs the real screen handlers exactly as user interaction would:
create product -> receive stock -> POS scan -> commit sale -> dashboard.
Verified against the actual handler methods; modal message boxes are
auto-dismissed (no display available in CI).

Skipped automatically when PySide6 cannot initialize a QApplication
(e.g. minimal environments without Qt system libraries).
"""

import os
import tempfile
import uuid as uuidlib

import pytest

pytest.importorskip("PySide6.QtWidgets")


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

TENANT = "11111111-1111-1111-1111-111111111111"
BARCODE = "6280000000018"


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture()
def window(qapp, tmp_path):
    import PySide6.QtWidgets as QtWidgets

    for name in ("information", "warning", "critical"):
        setattr(
            QtWidgets.QMessageBox, name,
            staticmethod(lambda *a, **k: None),
        )

    from desktop.ui.main_window import MainWindow
    from desktop.ui.ui_theme import apply_theme

    os.environ["GROCERY_ERP_HOME"] = str(tmp_path)
    from desktop.app.bootstrap import DesktopRuntime

    apply_theme(qapp)
    runtime = DesktopRuntime(data_dir=tmp_path)
    runtime.initialize()
    window = MainWindow(runtime, language="ar")
    window.show()
    yield window
    runtime.shutdown()
    os.environ.pop("GROCERY_ERP_HOME", None)


def _create_product(window):
    screen = window._screens["products"]
    screen._create_product(
        {
            "name": "Milk 1L",
            "name_ar": "حليب 1 لتر",
            "sku": f"MILK-{uuidlib.uuid4().hex[:6]}",
            "barcode": BARCODE,
            "cost": "500",
            "price": "1000",
            "tax_percent": "15",
            "min_stock": "10",
        }
    )
    assert screen.table.rowCount() >= 1


def _receive_stock(window):
    screen = window._screens["inventory"]
    row = window.runtime.db.query_one(
        "SELECT uuid FROM products WHERE tenant_id=? LIMIT 1", (screen._tenant_id(),)
    )
    screen._receive(row["uuid"], "24", "500")
    balance = window.runtime.db.query_one(
        "SELECT quantity FROM inventory_balances"
    )
    assert float(balance["quantity"]) == 24.0


def _commit_pos_sale(window):
    screen = window._screens["pos"]
    screen.search.setText(BARCODE)
    screen._on_scan()
    assert screen.table.rowCount() == 1
    screen._on_commit()
    balance = window.runtime.db.query_one(
        "SELECT quantity FROM inventory_balances"
    )["quantity"]
    assert float(balance) == 23.0
    events = window.runtime.db.query_all(
        "SELECT event_type FROM outbox_events"
    )
    types = {e["event_type"] for e in events}
    assert {"sale.created", "inventory.movement", "accounting.journal_posted"} <= types


def _dashboard_reflects_sale(window):
    window._on_navigate(0)
    label = window._screens["dashboard"].labels["today_sales"]
    assert label.text() not in {"0", "0.00 YER"}


def _navigate_every_screen(window):
    for index in range(window._nav.count()):
        window._on_navigate(index)


def test_full_offline_flow(window):
    _create_product(window)
    _receive_stock(window)
    _commit_pos_sale(window)
    _dashboard_reflects_sale(window)
    _navigate_every_screen(window)
