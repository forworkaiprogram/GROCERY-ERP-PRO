import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "desktop"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "desktop" / ".."))

from desktop.app.bootstrap import DesktopRuntime  # noqa: E402


@pytest.fixture()
def runtime(tmp_path):
    os.environ["GROCERY_ERP_HOME"] = str(tmp_path / "deviceA")
    rt = DesktopRuntime(data_dir=tmp_path / "deviceA")
    rt.initialize()
    yield rt
    rt.shutdown()
    os.environ.pop("GROCERY_ERP_HOME", None)


@pytest.fixture()
def seeded_products(runtime):
    tenant = runtime.device.get("tenant_id") or "local"
    runtime.db.execute(
        "UPDATE device_identity SET tenant_id=?, branch_id=?,"
        " registration_status='ACTIVE' WHERE id=1",
        ("11111111-1111-1111-1111-111111111111", "branch-1"),
    )
    runtime.products.insert(
        {
            "uuid": "aaaa1111-0000-0000-0000-000000000001",
            "tenant_id": "11111111-1111-1111-1111-111111111111",
            "sku": "MILK-1L",
            "name": "Milk 1L",
            "cost": "700",
            "price": "1000",
            "wholesale_price": "950",
            "min_price": "900",
            "default_unit": "PIECE",
            "tax_rate_bps": 0,
        }
    )
    runtime.products.insert(
        {
            "uuid": "aaaa1111-0000-0000-0000-000000000002",
            "tenant_id": "11111111-1111-1111-1111-111111111111",
            "sku": "OIL-1L",
            "name": "Cooking Oil 1L",
            "cost": "2000",
            "price": "2500",
            "min_price": "2400",
            "default_unit": "PIECE",
            "tax_rate_bps": 500,
        }
    )
    return "11111111-1111-1111-1111-111111111111"
