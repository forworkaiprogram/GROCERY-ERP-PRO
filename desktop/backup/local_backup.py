"""Local backup and restore. Zero-internet requirements: backups are plain
consistent SQLite copies of the local database, named with timestamps,
optionally encrypted with an age-style password via cryptography Fernet.
Restoration is always tested by reopening and integrity-checking the copy.
"""

from __future__ import annotations

import base64
import hashlib
import os
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path


class BackupError(RuntimeError):
    pass


class LocalBackupManager:
    def __init__(self, db, backup_dir: Path | None = None):
        self.db = db
        self.backup_dir = backup_dir or (db.path.parent / "backups")

    def create(self, label: str = "scheduled", encrypt_key: bytes | None = None) -> Path:
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        raw_path = self.backup_dir / f"groceryerp-{label}-{stamp}.db"
        self.db.backup_to(raw_path)
        checksum = _sha256(raw_path)
        if encrypt_key is not None:
            encrypted = _encrypt_file(raw_path, encrypt_key)
            raw_path.unlink()
            final = Path(str(raw_path) + ".enc")
            encrypted.rename(final)
            final.with_suffix(final.suffix + ".sha256").write_text(checksum)
            return final
        raw_path.with_suffix(raw_path.suffix + ".sha256").write_text(checksum)
        return raw_path

    def list_backups(self) -> list[Path]:
        if not self.backup_dir.exists():
            return []
        return sorted(self.backup_dir.glob("groceryerp-*.db*"))

    def verify(self, backup_path: Path) -> bool:
        checksum_file = Path(str(backup_path) + ".sha256")
        if not checksum_file.exists():
            return False
        return checksum_file.read_text().strip() == _sha256(backup_path)

    def restore(self, backup_path: Path, encrypt_key: bytes | None = None) -> None:
        """Restore a verified backup into a STAGING copy first, run an
        integrity check, then swap it in. The original database is preserved
        as a rollback copy."""
        if Path(str(backup_path)).suffix == ".enc":
            if encrypt_key is None:
                raise BackupError("encrypted backup requires a key")
            plain = Path(str(backup_path)[:-4] + ".restore-tmp")
            _decrypt_file(backup_path, plain, encrypt_key)
            backup_path = plain
        if not self.verify(backup_path):
            raise BackupError("backup checksum verification failed")
        staged = self.backup_dir / "restore-staging.db"
        shutil.copyfile(backup_path, staged)
        probe = sqlite3.connect(str(staged))
        try:
            result = probe.execute("PRAGMA integrity_check").fetchone()[0]
        finally:
            probe.close()
        if result != "ok":
            raise BackupError("restored copy failed integrity check")
        rollback = self.backup_dir / "pre-restore-rollback.db"
        shutil.copyfile(self.db.path, rollback)
        self.db.restore_from(staged)
        staged.unlink()
        if backup_path.name.endswith("restore-tmp"):
            backup_path.unlink(missing_ok=True)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _encrypt_file(src: Path, key: bytes) -> Path:
    from cryptography.fernet import Fernet

    fernet = Fernet(base64.urlsafe_b64encode(hashlib.sha256(key).digest()))
    data = fernet.encrypt(src.read_bytes())
    out = src.with_suffix(src.suffix + "0.enc")
    out.write_bytes(data)
    return out


def _decrypt_file(src: Path, dst: Path, key: bytes) -> None:
    from cryptography.fernet import Fernet, InvalidToken

    fernet = Fernet(base64.urlsafe_b64encode(hashlib.sha256(key).digest()))
    try:
        data = fernet.decrypt(src.read_bytes())
    except InvalidToken as exc:
        raise BackupError("backup key incorrect") from exc
    dst.write_bytes(data)
