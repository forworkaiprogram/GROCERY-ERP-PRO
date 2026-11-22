"""Update Center service: check, download (resumable), verify, stage.

No package is ever executed or trusted purely because it downloaded
successfully: HTTPS-only download to a staging directory, streamed SHA-256,
and signed-manifest verification gates. Installation itself (running the
staged installer) happens through the packaging workflow after
pre-install safeguards (see updates/preinstall.py and documentation/updates).
"""

from __future__ import annotations

import json
import urllib.request
from pathlib import Path

from ..database.db import app_data_dir
from ..security.cloud_signing import Ed25519PublicKey
from .manifest import ManifestError, VersionError, verify_manifest, verify_package

STAGING_DIRNAME = "update-staging"


class UpdateCheckError(RuntimeError):
    pass


class UpdateCenterService:
    def __init__(self, db, public_key: Ed25519PublicKey, update_base_url: str,
                 staging_dir: Path | None = None):
        self.db = db
        self.public_key = public_key
        self.update_base_url = update_base_url.rstrip("/")
        self.staging_dir = staging_dir or (app_data_dir() / STAGING_DIRNAME)

    # ---- status ---------------------------------------------------------
    def status(self) -> dict:
        row = self.db.query_one("SELECT * FROM update_status WHERE id=1")
        return dict(row) if row else {}

    def ensure_status_row(self, current_version: str, local_schema_version: int) -> dict:
        self.db.execute(
            "INSERT OR IGNORE INTO update_status (id, current_version,"
            " current_schema_version) VALUES (1,?,?)",
            (current_version, local_schema_version),
        )
        return self.status()

    # ---- check -----------------------------------------------------------
    def check_for_updates(self, channel: str = "stable") -> dict | None:
        """Fetch the signed manifest list and return the newest verified
        compatible manifest, or None. Any signature failure rejects the
        manifest entirely."""
        status = self.ensure_status_row(
            current_version=self.status().get("current_version", "0.0.0"),
            local_schema_version=int(self.status().get("current_schema_version", 0)),
        )
        try:
            request = urllib.request.Request(
                f"{self.update_base_url}/api/v1/updates/releases/?channel={channel}",
                method="GET",
            )
            with urllib.request.urlopen(request, timeout=15) as response:
                releases = json.loads(response.read().decode("utf-8"))["releases"]
        except Exception as exc:
            self.db.execute(
                "UPDATE update_status SET last_check_at=datetime('now'), last_error=?"
                " WHERE id=1",
                (f"update check failed: {exc}",),
            )
            raise UpdateCheckError(f"update check failed: {exc}") from exc

        verified = None
        for signed in releases:
            try:
                payload = verify_manifest(signed, self.public_key)
            except ManifestError:
                continue  # untrusted manifest is dropped, never applied
            try:
                from .manifest import check_compatibility

                check_compatibility(
                    payload,
                    current_version=status["current_version"],
                    local_schema_version=int(status["current_schema_version"]),
                )
            except VersionError:
                continue
            if verified is None or _key(payload) > _key(verified):
                verified = payload
        self.db.execute(
            "UPDATE update_status SET last_check_at=datetime('now'), last_error=NULL,"
            " available_version=?, available_manifest=?, download_state=CASE"
            " WHEN ? IS NULL THEN download_state ELSE 'IDLE' END WHERE id=1",
            (
                verified["version"] if verified else None,
                json.dumps({"payload": verified}, sort_keys=True) if verified else None,
                verified["version"] if verified else None,
            ),
        )
        return verified

    # ---- download ---------------------------------------------------------
    def download_staged(self, manifest: dict, resume: bool = True) -> Path:
        """Resumable HTTPS download into the staging directory followed by
        streamed SHA-256 verification. Returns the staged path."""
        self.staging_dir.mkdir(parents=True, exist_ok=True)
        target = self.staging_dir / f"groceryerp-{manifest['version']}.pkg"
        part = Path(str(target) + ".part")
        url = manifest["package_url"]
        if not url.startswith("https://") and "localhost" not in url and "127.0.0.1" not in url:
            raise UpdateCheckError("refusing non-HTTPS package URL")

        from ..updates.resumable import http_download_resumable

        self.db.execute(
            "UPDATE update_status SET download_state='DOWNLOADING', last_error=NULL WHERE id=1"
        )
        try:
            http_download_resumable(url, part, expected_size=int(manifest["package_size"]))
            verify_package(part, manifest["sha256"])
            part.replace(target)
        except Exception as exc:
            self.db.execute(
                "UPDATE update_status SET download_state='FAILED', last_error=? WHERE id=1",
                (str(exc),),
            )
            raise
        self.db.execute(
            "UPDATE update_status SET download_state='STAGED', staged_path=?,"
            " staged_checksum=? WHERE id=1",
            (str(target), manifest["sha256"]),
        )
        return target


def _key(payload: dict):
    from .manifest import parse_version

    return parse_version(payload["version"])
