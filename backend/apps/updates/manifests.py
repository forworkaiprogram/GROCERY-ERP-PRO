"""Update-manifest signing on the release server.

Mirrors the desktop verifier contract (desktop/updates/manifest.py):
canonical JSON (sorted keys, no whitespace) signed with Ed25519, delivered
as ``{"payload": ..., "signature": base64}``.
"""

from __future__ import annotations

import base64
import json

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)


class SigningKeyUnavailable(RuntimeError):
    pass


def load_signing_key(path) -> Ed25519PrivateKey:
    try:
        data = open(path, "rb").read()
    except OSError as exc:
        raise SigningKeyUnavailable(
            f"update signing key unavailable at {path}: {exc}"
        ) from exc
    key = serialization.load_pem_private_key(data, password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise SigningKeyUnavailable(
            f"update signing key at {path} is not an Ed25519 private key"
        )
    return key


def canonical_bytes(payload: dict) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sign_manifest(payload: dict, key: Ed25519PrivateKey) -> dict:
    return {
        "payload": payload,
        "signature": base64.b64encode(key.sign(canonical_bytes(payload))).decode(),
    }
