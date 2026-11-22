"""Signed release manifest verification.

A release manifest is canonical JSON signed with the platform Ed25519 key.
The desktop refuses to trust any manifest whose signature, checksums, or
compatibility fields fail validation. The private signing key exists only on
the cloud release server.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from ..security.cloud_signing import Ed25519PublicKey, verify_signature

REQUIRED_FIELDS = (
    "app_id",
    "version",
    "build",
    "channel",
    "package_url",
    "package_size",
    "sha256",
    "min_schema_version",
    "max_schema_version",
    "required",
    "published_at",
)
CHANNELS = frozenset({"stable", "beta", "internal"})


class ManifestError(ValueError):
    pass


class VersionError(ManifestError):
    pass


def canonical_bytes(payload: dict) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def verify_manifest(signed: dict, public_key: Ed25519PublicKey) -> dict:
    """signed: {payload, signature}. Returns the payload. Raises ManifestError."""
    payload = signed.get("payload")
    signature = signed.get("signature")
    if payload is None or signature is None:
        raise ManifestError("malformed manifest")
    missing = [f for f in REQUIRED_FIELDS if f not in payload]
    if missing:
        raise ManifestError(f"manifest missing fields: {missing}")
    if payload.get("app_id") != "grocery-erp-pro":
        raise ManifestError("manifest is for a different application")
    if payload.get("channel") not in CHANNELS:
        raise ManifestError(f"unknown release channel {payload.get('channel')!r}")
    if int(payload.get("package_size", -1)) <= 0:
        raise ManifestError("package_size must be positive")
    sha = str(payload.get("sha256", ""))
    if len(sha) != 64 or any(c not in "0123456789abcdef" for c in sha):
        raise ManifestError("sha256 checksum malformed")
    if not verify_signature(canonical_bytes(payload), signature, public_key):
        raise ManifestError("manifest signature invalid")
    return payload


def parse_version(version: str) -> tuple:
    parts = []
    for part in str(version).split("."):
        numeric = "".join(ch for ch in part if ch.isdigit())
        parts.append(int(numeric) if numeric else 0)
    return tuple(parts)


def check_compatibility(payload: dict, *, current_version: str, local_schema_version: int) -> dict:
    """Returns the compatibility result; NEVER mutates the local database here."""
    if parse_version(payload["version"]) <= parse_version(current_version):
        raise VersionError(
            f"update {payload['version']} is not newer than installed"
            f" {current_version} (anti-downgrade)"
        )
    declared_min = int(payload["min_schema_version"])
    declared_max = int(payload["max_schema_version"])
    if not (declared_min <= local_schema_version <= declared_max):
        raise VersionError(
            f"local schema v{local_schema_version} is outside the supported range"
            f" [{declared_min}, {declared_max}] for update {payload['version']}"
        )
    return {"compatible": True}


def verify_package(package_path: Path, expected_sha256: str) -> str:
    """Streamed SHA-256 verification. Raises on mismatch."""
    digest = hashlib.sha256()
    with open(package_path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    actual = digest.hexdigest()
    if actual != expected_sha256:
        raise ManifestError(f"package checksum mismatch: {actual}")
    return actual
