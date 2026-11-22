"""Per-installation device identity.

Generated once per installation and stored ONLY in that installation's local
database. Two installations on two machines therefore have different
identities and different database files by construction.
"""

from __future__ import annotations

import platform
import uuid as uuidlib


class DeviceIdentityService:
    def __init__(self, db):
        self.db = db

    def ensure_identity(self, device_name: str | None = None) -> dict:
        row = self.db.query_one("SELECT * FROM device_identity WHERE id=1")
        if row:
            return dict(row)
        device_id = str(uuidlib.uuid4())
        name = device_name or f"POS-{platform.node() or 'WINDOWS-PC'}"
        self.db.execute(
            "INSERT INTO device_identity (device_id, device_name) VALUES (?,?)",
            (device_id, name),
        )
        return dict(self.db.query_one("SELECT * FROM device_identity WHERE id=1"))

    def get(self) -> dict | None:
        row = self.db.query_one("SELECT * FROM device_identity WHERE id=1")
        return dict(row) if row else None

    def apply_registration(
        self, *, tenant_id: str, branch_id: str, warehouse_id: str | None, status: str
    ) -> dict:
        """Called after the server authorized this device (enrollment flow).
        A locally-provisioned registration is never treated as authorized
        until the server response is stored with status='ACTIVE'."""
        self.db.execute(
            "UPDATE device_identity SET tenant_id=?, branch_id=?, warehouse_id=?,"
            " registration_status=?, registered_at=datetime('now') WHERE id=1",
            (tenant_id, branch_id, warehouse_id, status),
        )
        return self.get()

    def is_authorized(self) -> bool:
        row = self.get()
        return bool(row) and row["registration_status"] == "ACTIVE" and not row["revoked"]

    def revoke(self) -> None:
        self.db.execute(
            "UPDATE device_identity SET revoked=1, registration_status='REVOKED' WHERE id=1"
        )
