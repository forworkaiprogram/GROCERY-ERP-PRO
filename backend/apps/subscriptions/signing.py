"""Ed25519 signing of entitlement snapshots on the authority (cloud) side.

Canonicalization and envelope shape are the exact inverse of the desktop
verifier (desktop/security/cloud_signing.py +
desktop/services/entitlements.py): canonical JSON with sorted keys and no
whitespace, base64 signature over the canonical bytes.
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
            f"entitlement signing key unavailable at {path}: {exc}"
        ) from exc
    key = serialization.load_pem_private_key(data, password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise SigningKeyUnavailable(
            f"entitlement signing key at {path} is not an Ed25519 private key"
        )
    return key


def canonical_bytes(payload: dict) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sign_payload(payload: dict, key: Ed25519PrivateKey) -> dict:
    return {
        "payload": payload,
        "signature": base64.b64encode(key.sign(canonical_bytes(payload))).decode(),
    }


def verify_with_public_key(signed: dict, public_key_pem: bytes) -> bool:
    try:
        key = serialization.load_pem_public_key(public_key_pem)
        signature = base64.b64decode(signed["signature"])
        key.verify(signature, canonical_bytes(signed["payload"]))
        return True
    except Exception:
        return False
