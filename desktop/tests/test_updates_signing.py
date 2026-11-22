import base64
import hashlib
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization

from desktop.security.cloud_signing import load_public_key
from desktop.updates.manifest import (
    ManifestError,
    canonical_bytes,
    check_compatibility,
    verify_manifest,
    verify_package,
)
from desktop.updates.resumable import http_download_resumable

SERVER_KEY = Ed25519PrivateKey.generate()
OTHER_KEY = Ed25519PrivateKey.generate()


def _sign(payload: dict, key: Ed25519PrivateKey = SERVER_KEY) -> dict:
    signature = base64.b64encode(key.sign(canonical_bytes(payload))).decode()
    return {"payload": payload, "signature": signature}


def _payload(**overrides):
    payload = {
        "app_id": "grocery-erp-pro",
        "version": "1.1.0",
        "build": 42,
        "channel": "stable",
        "package_url": "https://updates.example.com/pkg/1.1.0.exe",
        "package_size": 186000000,
        "sha256": "ab" * 32,
        "min_schema_version": 1,
        "max_schema_version": 3,
        "required": False,
        "published_at": "2025-01-20T09:00:00Z",
    }
    payload.update(overrides)
    return payload


def _pubkey():
    pem = SERVER_KEY.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    return load_public_key(pem)


def test_valid_signed_manifest_accepted():
    payload = verify_manifest(_sign(_payload()), _pubkey())
    assert payload["version"] == "1.1.0"


def test_unsigned_or_tampered_manifest_rejected():
    with pytest.raises(ManifestError):
        verify_manifest({"payload": _payload(), "signature": "AAAA"}, _pubkey())
    tampered = _sign(_payload())
    tampered["payload"]["version"] = "9.9.9"
    with pytest.raises(ManifestError):
        verify_manifest(tampered, _pubkey())


def test_wrong_signing_key_rejected():
    with pytest.raises(ManifestError):
        verify_manifest(_sign(_payload(), OTHER_KEY), _pubkey())


def test_missing_required_fields_rejected():
    bad = _sign(_payload())
    del bad["payload"]["channel"]
    with pytest.raises(ManifestError):
        verify_manifest(bad, _pubkey())


def test_compatibility_and_anti_downgrade():
    payload = _payload()
    assert check_compatibility(
        payload, current_version="1.0.0", local_schema_version=2
    ) == {"compatible": True}
    with pytest.raises(ManifestError):
        check_compatibility(payload, current_version="1.1.0", local_schema_version=2)
    with pytest.raises(ManifestError):
        check_compatibility(payload, current_version="1.0.0", local_schema_version=9)


def test_package_checksum_verification(tmp_path):
    pkg = tmp_path / "pkg.bin"
    pkg.write_bytes(b"installer-bytes")
    good = hashlib.sha256(pkg.read_bytes()).hexdigest()
    assert verify_package(pkg, good) == good
    with pytest.raises(ManifestError):
        verify_package(pkg, "cd" * 32)


class _RangeServer(BaseHTTPRequestHandler):
    data = (b"PKGDATA" * 5000)[:35000]

    def do_GET(self):
        rng = self.headers.get("Range")
        start = 0
        if rng and rng.startswith("bytes="):
            start = int(rng.removeprefix("bytes=").split("-")[0])
            partial = self.data[start:]
            if start >= len(self.data):
                self.send_response(416)
                self.end_headers()
                return
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{len(self.data)-1}/{len(self.data)}")
        else:
            partial = self.data
            self.send_response(200)
        self.send_header("Content-Length", str(len(partial)))
        self.end_headers()
        self.wfile.write(partial)

    def log_message(self, *a):
        pass


@pytest.fixture()
def http_server():
    server = HTTPServer(("127.0.0.1", 0), _RangeServer)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}/pkg.exe"
    server.shutdown()


def test_resumable_download(http_server, tmp_path):
    target = tmp_path / "out.part"
    # interruption 1: partial file written manually
    target.write_bytes(_RangeServer.data[:10000])
    http_download_resumable(http_server, target, expected_size=len(_RangeServer.data))
    assert target.read_bytes() == _RangeServer.data
