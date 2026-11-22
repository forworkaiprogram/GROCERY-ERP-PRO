"""Composition root (Qt-free). Builds the local runtime: database,
migrations, device identity, engines, and services. The Qt application
imports this and hands instances to the UI layer — keeping the entire
business core importable and testable without Qt.
"""

from __future__ import annotations

from pathlib import Path

from ..backup.local_backup import LocalBackupManager
from ..business_logic.accounting import AccountingEngine
from ..business_logic.inventory import InventoryLedger
from ..business_logic.repositories import (
    CustomerRepository,
    ProductRepository,
    SupplierRepository,
)
from ..business_logic.sale_engine import SaleEngine
from ..database.db import Database, app_data_dir
from ..security.device_identity import DeviceIdentityService
from ..synchronization.engine import SyncEngine
from ..synchronization.transport import HttpsSyncTransport
from ..updates.service import UpdateCenterService
from ..synchronization.outbox import Outbox

APP_VERSION = "1.0.0"
APP_SCHEMA_VERSION = 1


class DesktopRuntime:
    def __init__(self, data_dir: Path | None = None, update_base_url: str = "",
                 public_key=None):
        if data_dir is not None:
            import os

            os.environ["GROCERY_ERP_HOME"] = str(data_dir)
        self.data_dir = Path(data_dir) if data_dir else app_data_dir()
        self.db = Database(self.data_dir / "grocery_erp.db")
        self.update_base_url = update_base_url
        self.applied_migrations: list[int] = []

    def initialize(self) -> None:
        self.applied_migrations = self.db.apply_migrations()
        self.device = DeviceIdentityService(self.db).ensure_identity()
        self.products = ProductRepository(self.db)
        self.customers = CustomerRepository(self.db)
        self.suppliers = SupplierRepository(self.db)
        self.sales = SaleEngine(self.db)
        self.outbox = Outbox(self.db)
        self.inventory = InventoryLedger(self.db)
        self.accounting = AccountingEngine(self.db)
        self.backup = LocalBackupManager(self.db)
        self.db.execute(
            "INSERT OR IGNORE INTO app_config (key, value) VALUES ('app_version', ?)",
            (APP_VERSION,),
        )

    def mark_version_installed(self, version: str, schema_version: int) -> None:
        self.db.execute(
            "INSERT INTO app_config (key, value) VALUES ('app_version', ?)"
            " ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (version,),
        )
        self.db.execute(
            "INSERT OR IGNORE INTO sync_checkpoints (id) VALUES (1)"
        )

    def build_sync_engine(self, transport=None) -> SyncEngine:
        transport = transport or HttpsSyncTransport(self.update_base_url)
        token_getter = self._device_token_getter()
        return SyncEngine(self.db, transport, device_token_getter=token_getter)

    def build_update_center(self, public_key=None) -> UpdateCenterService:
        from ..security.cloud_signing import DEFAULT_PUBLIC_KEY_PATH

        key = public_key or DEFAULT_PUBLIC_KEY_PATH
        return UpdateCenterService(self.db, key, self.update_base_url)

    def _device_token_getter(self):
        row = self.db.query_one(
            "SELECT token_hash FROM auth_cache WHERE id=1"
        )

        def getter():
            from ..security.secrets import SecretStore

            return SecretStore().get("device_token")

        return getter

    def shutdown(self) -> None:
        self.db.close()
