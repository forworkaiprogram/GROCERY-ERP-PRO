"""Ed25519 signature verification for server-signed artifacts
(entitlement snapshots, update manifests). The EXE embeds ONLY the public
verification key; the private signing key never leaves the cloud.
"""

from __future__ import annotations

import base64
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

DEFAULT_PUBLIC_KEY_PATH = Path(__file__).resolve().parent / "public_keys" / "cloud_ed25519.pub"


def load_public_key(pem_or_path: str | Path | bytes) -> Ed25519PublicKey:
    from cryptography.hazmat.primitives import serialization

    if isinstance(pem_or_path, (str, Path)) and Path(pem_or_path).exists():
        data = Path(pem_or_path).read_bytes()
    elif isinstance(pem_or_path, (str, Path)):
        pem_path = Path(pem_or_path)
        data = pem_path.read_bytes()
    else:
        data = pem_or_path
    return serialization.load_pem_public_key(data)


def verify_signature(payload: bytes, signature_b64: str, public_key: Ed25519PublicKey) -> bool:
    try:
        signature = base64.b64decode(signature_b64)
        public_key.verify(signature, payload)
        return True
    except (InvalidSignature, ValueError, TypeError):
        return False
