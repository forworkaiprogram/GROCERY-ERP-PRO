"""Provisioning tool for the platform Ed25519 signing keys.

Run ONCE on the release/entitlement signing server (never on end-user
machines):

    python scripts/generate_signing_keys.py --server-keys-dir /secure/keys \
        --desktop-pub desktop/security/public_keys/cloud_ed25519.pub

The private keys stay on the server; only the public key is copied into the
desktop source tree so it is embedded in the EXE during packaging.
If the keys directory already contains keys they are left untouched.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

NAMES = ("update_signing_key", "entitlement_signing_key")


def write_if_absent(path: Path, data: bytes) -> bool:
    if path.exists():
        print(f"exists, kept: {path}")
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    print(f"written: {path}")
    return True


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--server-keys-dir", required=True)
    parser.add_argument("--desktop-pub", required=True)
    args = parser.parse_args()

    server_dir = Path(args.server_keys_dir)
    for name in NAMES:
        private_path = server_dir / f"{name}.pem"
        if private_path.exists():
            existing = serialization.load_pem_private_key(
                private_path.read_bytes(), password=None
            )
            key = existing
        else:
            key = Ed25519PrivateKey.generate()
            private_pem = key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            )
            write_if_absent(private_path, private_pem)
        public_pem = key.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        write_if_absent(server_dir / f"{name}.public.pem", public_pem)

    desktop_pub = Path(args.desktop_pub)
    # The desktop embeds ONE public key (same platform key for updates and
    # entitlements in this deployment; rotate both together if split).
    update_pub = (server_dir / "update_signing_key.public.pem").read_bytes()
    desktop_pub.parent.mkdir(parents=True, exist_ok=True)
    desktop_pub.write_bytes(update_pub)
    print(f"desktop public key written: {desktop_pub}")


if __name__ == "__main__":
    main()
