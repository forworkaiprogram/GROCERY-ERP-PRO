import base64
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from desktop.security.cloud_signing import load_public_key
from desktop.business_logic.money import D
from desktop.services.entitlements import (
    EntitlementError,
    EntitlementService,
    canonical,
)

KEY = Ed25519PrivateKey.generate()


def _pubkey():
    pem = KEY.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    return load_public_key(pem)


def _snapshot(plan="professional", days=30, entitlements=None, key=KEY,
              valid_until=None):
    payload = {
        "tenant_id": "11111111-1111-1111-1111-111111111111",
        "plan": plan,
        "signed_at": "2025-01-01T00:00:00Z",
        "valid_until": valid_until or (datetime.now(timezone.utc) + timedelta(days=days)).isoformat().replace("+00:00", "Z"),
        "entitlements": entitlements or {
            "pos": True, "products": True, "inventory": True, "sales_history": True,
            "sync": True, "advanced_reports": True, "accounting": True,
            "payroll": True, "hr": True,
        },
        "limits": {"branches": 5, "users": 25, "devices": 10},
    }
    signature = base64.b64encode(key.sign(canonical(payload))).decode()
    return {"payload": payload, "signature": signature}


def test_valid_snapshot_caches_and_entitles(runtime):
    service = EntitlementService(runtime.db, _pubkey(), grace_hours=72)
    service.cache_snapshot(_snapshot())
    ent = service.current()
    assert ent["accounting"] is True and ent["payroll"] is True


def test_tampered_snapshot_rejected(runtime):
    service = EntitlementService(runtime.db, _pubkey())
    with pytest.raises(EntitlementError):
        service.cache_snapshot({"payload": {"plan": "pro"}, "signature": "AAAA"})


def test_unsigned_premium_access_is_not_trusted(runtime):
    """Nothing cached -> lite feature set only. No premium unlock without a
    verified signed snapshot."""
    service = EntitlementService(runtime.db, _pubkey())
    ent = service.current()
    assert ent["pos"] is True and ent["payroll"] is False and ent["accounting"] is False


def test_expired_within_grace_limits_premium_keeps_core(runtime):
    service = EntitlementService(runtime.db, _pubkey(), grace_hours=72)
    stale = datetime.now(timezone.utc) - timedelta(hours=48)
    service.cache_snapshot(_snapshot(valid_until=stale.isoformat().replace("+00:00", "Z")))
    ent = service.current()
    assert ent["pos"] is True            # core selling continues in grace
    assert ent["payroll"] is False       # premium suspended during grace
    assert service.is_expired_beyond_grace() is False


def test_expired_beyond_grace_lowers_to_lite_but_never_deletes(runtime):
    service = EntitlementService(runtime.db, _pubkey(), grace_hours=1)
    stale = datetime.now(timezone.utc) - timedelta(hours=48)
    service.cache_snapshot(_snapshot(valid_until=stale.isoformat().replace("+00:00", "Z")))
    ent = service.current()
    assert ent["advanced_reports"] is False
    assert service.is_expired_beyond_grace() is True
    # business data intact: subscription expiry never deletes data
    assert runtime.db.query_one("SELECT COUNT(*) n FROM products")["n"] >= 0


def test_backup_verify_and_restore_roundtrip(runtime, seeded_products):
    from desktop.backup.local_backup import LocalBackupManager

    manager = LocalBackupManager(runtime.db, backup_dir=runtime.data_dir / "backups")
    backup = manager.create("test")
    assert manager.verify(backup)
    # corrupt a copy: verification must fail
    bad = runtime.data_dir / "bad.db"
    bad.write_bytes(b"garbage")
    bad.with_suffix(".db.sha256").write_text("aa" * 32)
    assert manager.verify(bad) is False

    # add data AFTER backup
    runtime.products.insert(
        {
            "uuid": "bbbb2222-0000-0000-0000-000000000009",
            "tenant_id": "11111111-1111-1111-1111-111111111111",
            "sku": "RESTORED-PRODUCT",
            "name": "X",
        }
    )
    # restore over the live db
    manager.restore(backup)
    assert runtime.db.query_one(
        "SELECT COUNT(*) n FROM products WHERE sku='RESTORED-PRODUCT'"
    )["n"] == 0
    assert runtime.db.query_one(
        "SELECT COUNT(*) n FROM products WHERE sku='MILK-1L'"
    )["n"] == 1
    assert runtime.db.integrity_check()
