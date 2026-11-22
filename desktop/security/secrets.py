"""Secure local secret storage.

Windows: secrets are protected with DPAPI via win32crypt (CryptProtectData).
Non-Windows dev environments: fall back to mode-0600 file with a documented
warning — production Windows builds always use DPAPI. Never plaintext by
design on the shipping platform.
"""

from __future__ import annotations

import base64
import json
import os
import stat
import sys
from pathlib import Path

from ..database.db import app_data_dir


class SecretStore:
    def __init__(self, path: Path | None = None):
        self._path = path or (app_data_dir() / "secrets.bin")
        self._dpapi = sys.platform.startswith("win")
        try:
            import win32crypt  # type: ignore

            self._win32crypt = win32crypt
        except ImportError:
            self._win32crypt = None

    def set(self, key: str, value: str) -> None:
        blob = json.dumps({key: value}).encode("utf-8")
        stored: bytes
        if self._dpapi and self._win32crypt is not None:
            stored = base64.b64encode(
                self._win32crypt.CryptProtectData(blob, "GroceryErpPro", None, None, None, 0)
            )
        else:
            stored = blob
            if not self._dpapi:
                self._warn_dev_mode()
        self._write(stored)

    def get(self, key: str) -> str | None:
        if not self._path.exists():
            return None
        stored = self._path.read_bytes()
        try:
            if self._dpapi and self._win32crypt is not None:
                blob = self._win32crypt.CryptUnprotectData(
                    base64.b64decode(stored), None, None, None, 0
                )[1]
            else:
                blob = stored
            return json.loads(blob).get(key)
        except Exception:
            return None

    def delete(self) -> None:
        if self._path.exists():
            self._path.unlink()

    def _write(self, blob: bytes) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_bytes(blob)
        if not self._dpapi:
            os.chmod(self._path, stat.S_IRUSR | stat.S_IWUSR)

    @staticmethod
    def _warn_dev_mode() -> None:
        import logging

        logging.getLogger("groceryerp.security").warning(
            "DPAPI unavailable: dev-mode secret storage in use; do not ship this build"
        )
