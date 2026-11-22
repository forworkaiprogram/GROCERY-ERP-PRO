import sqlite3

import pytest

from desktop.app.bootstrap import DesktopRuntime


def test_two_installations_have_distinct_databases_and_device_ids(tmp_path):
    rt_a = DesktopRuntime(data_dir=tmp_path / "A")
    rt_a.initialize()
    rt_b = DesktopRuntime(data_dir=tmp_path / "B")
    rt_b.initialize()
    a, b = rt_a.device, rt_b.device
    assert a["device_id"] != b["device_id"]
    assert rt_a.db.path != rt_b.db.path
    assert rt_a.db.path.is_relative_to(tmp_path / "A")
    assert rt_b.db.path.is_relative_to(tmp_path / "B")
    rt_a.shutdown()
    rt_b.shutdown()


def test_database_survives_reopen(tmp_path):
    rt = DesktopRuntime(data_dir=tmp_path)
    rt.initialize()
    db_path = rt.db.path
    first_device = rt.device["device_id"]
    rt.db.execute(
        "INSERT INTO notifications (category, message) VALUES ('TEST', 'persist me')"
    )
    rt.shutdown()
    rt2 = DesktopRuntime(data_dir=tmp_path)
    rt2.initialize()
    assert rt2.db.path == db_path
    assert rt2.device["device_id"] == first_device
    assert rt2.db.query_one(
        "SELECT message FROM notifications WHERE category='TEST'"
    )["message"] == "persist me"
    rt2.shutdown()


def test_migrations_are_idempotent(tmp_path):
    rt = DesktopRuntime(data_dir=tmp_path)
    first_run = rt.initialize() or rt.applied_migrations
    assert first_run, "first initialize must apply migrations"
    before = rt.db.schema_version()
    rt.initialize() if False else rt.db.apply_migrations()
    assert rt.db.schema_version() == before
    rt.shutdown()


def test_foreign_keys_enforced(tmp_path):
    rt = DesktopRuntime(data_dir=tmp_path)
    rt.initialize()
    with pytest.raises(sqlite3.IntegrityError):
        rt.db.execute(
            "INSERT INTO sale_items (sale_uuid, product_uuid, quantity, unit_price,"
            " line_total) VALUES ('nope', 'nope', '1', '1', '1')"
        )
    rt.shutdown()
