"""Pre-install safeguard checklist (spec 12.5).

build_preinstall_report runs every safety check and returns a report that
the installer workflow requires to be fully green before launching the
staged installer. It performs NO installation and touches NO business data.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from ..database.db import Database
from .manifest import verify_package


def build_preinstall_report(
    db: Database,
    staged_path: Path,
    expected_sha256: str,
    manifest: dict,
    min_free_bytes: int = 512 * 1024 * 1024,
    required_disk_multiplier: float = 2.5,
) -> dict:
    report = {
        "checksum_verified": False,
        "signature_fields_present": bool(
            manifest.get("sha256") and manifest.get("min_schema_version") is not None
        ),
        "disk_space_ok": False,
        "database_integrity_ok": False,
        "foreign_keys_ok": False,
        "schema_compatible": False,
        "backup_target_ready": False,
        "pending_outbox_count": 0,
        "pending_unsynced_sales": 0,
        "previous_app_version": None,
        "ok": False,
    }
    # 1-2. Re-verify package integrity right before installation.
    report["checksum_verified"] = verify_package(staged_path, expected_sha256) == expected_sha256

    # 3. Disk space for the new app plus extraction headroom.
    free = shutil.disk_usage(staged_path.parent).free
    needed = int(int(manifest["package_size"]) * required_disk_multiplier)
    report["disk_space_ok"] = free >= max(min_free_bytes, needed)

    # 4-5. Local DB health and schema compatibility.
    report["database_integrity_ok"] = db.integrity_check()
    report["foreign_keys_ok"] = db.foreign_key_violations() == 0
    declared_min = int(manifest["min_schema_version"])
    declared_max = int(manifest["max_schema_version"])
    report["schema_compatible"] = declared_min <= db.schema_version() <= declared_max

    # 6-7. Surfaces active work the UI must settle before install; pending
    # outbox events and unsynced sales are preserved by the pre-install
    # backup (a consistent online copy of the whole database).
    row = db.query_one("SELECT COUNT(*) AS n FROM outbox_events WHERE state='PENDING'")
    report["pending_outbox_count"] = int(row["n"])
    row = db.query_one("SELECT COUNT(*) AS n FROM sales WHERE sync_state <> 'ACKNOWLEDGED'")
    report["pending_unsynced_sales"] = int(row["n"])

    # 8. A verified backup target must exist; the caller creates it with
    # LocalBackupManager BEFORE installation.
    backup_dir = db.path.parent / "pre-update-backups"
    report["backup_target_ready"] = backup_dir.exists() and any(backup_dir.iterdir())

    row = db.query_one("SELECT value FROM app_config WHERE key='app_version'")
    report["previous_app_version"] = row["value"] if row else None

    report["ok"] = (
        report["checksum_verified"]
        and report["signature_fields_present"]
        and report["disk_space_ok"]
        and report["database_integrity_ok"]
        and report["foreign_keys_ok"]
        and report["schema_compatible"]
        and report["backup_target_ready"]
    )
    return report
