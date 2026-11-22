"""Startup smoke tests for the composition root.

Guards the exact call path used by desktop.app.main.main(): the runtime
is built with defaults, initialized, then build_sync_engine() and
build_update_center() must succeed without configuration.
"""

import os

import pytest

from desktop.app.bootstrap import DesktopRuntime


@pytest.fixture()
def clean_home(tmp_path):
    os.environ["GROCERY_ERP_HOME"] = str(tmp_path / "device")
    yield tmp_path / "device"
    os.environ.pop("GROCERY_ERP_HOME", None)


def test_runtime_builds_sync_engine_with_defaults(clean_home):
    rt = DesktopRuntime(data_dir=clean_home)
    rt.initialize()
    try:
        engine = rt.build_sync_engine()
        assert engine is not None
        assert engine.outbox is not None
    finally:
        rt.shutdown()


def test_missing_base_url_reports_offline_not_crash(clean_home):
    from desktop.synchronization.engine import SyncEngine
    from desktop.synchronization.transport import HttpsSyncTransport

    rt = DesktopRuntime(data_dir=clean_home)
    rt.initialize()
    try:
        engine = rt.build_sync_engine()
        assert isinstance(engine, SyncEngine)
        transport = HttpsSyncTransport(rt.update_base_url)
        assert transport.check_connectivity() is False
        result = engine.run_once()
        assert result["submitted"] == 0
    finally:
        rt.shutdown()


def test_missing_base_url_pending_events_marked_retry_not_discarded(clean_home):
    from desktop.synchronization.transport import HttpsSyncTransport, TransportError

    rt = DesktopRuntime(data_dir=clean_home)
    rt.initialize()
    try:
        device_id = rt.device["device_id"]
        with rt.db.transaction() as db:
            rt.outbox.append(
                tenant_id="11111111-1111-1111-1111-111111111111",
                device_id=device_id,
                event_type="sale.created",
                payload={"sale_id": "s1", "total": "100.00", "version": 1},
            )
        transport = HttpsSyncTransport(rt.update_base_url)
        with pytest.raises(TransportError):
            transport.post_events([], "token")
        pending = rt.db.query_all(
            "SELECT state FROM outbox_events WHERE state != 'ACKNOWLEDGED'"
        )
        assert len(pending) >= 1
    finally:
        rt.shutdown()


def test_update_center_accepts_server_side_test_key(clean_home, tmp_path):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (
        Ed25519PrivateKey,
    )
    from desktop.updates.service import UpdateCenterService

    rt = DesktopRuntime(data_dir=clean_home)
    rt.initialize()
    try:
        private = Ed25519PrivateKey.generate()
        from cryptography.hazmat.primitives import serialization

        public_pem = private.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        key_path = clean_home / "test_pub.pem"
        key_path.write_bytes(public_pem)
        from desktop.security.cloud_signing import load_public_key

        center = rt.build_update_center(public_key=load_public_key(key_path))
        assert isinstance(center, UpdateCenterService)
    finally:
        rt.shutdown()
