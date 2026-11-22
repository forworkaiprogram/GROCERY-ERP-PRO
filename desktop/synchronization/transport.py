"""Transport abstraction for synchronization.

`HttpsSyncTransport` ships with the product; tests inject in-memory
transports. The transport never interprets business data — it only submits
event envelopes and returns acknowledgements.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request


class TransportError(ConnectionError):
    pass


class SyncTransport:
    def post_events(self, events: list[dict], device_token: str) -> list[dict]:
        raise NotImplementedError

    def check_connectivity(self) -> bool:
        raise NotImplementedError


class HttpsSyncTransport(SyncTransport):
    def __init__(self, base_url: str, timeout: float = 15.0):
        self.base_url = (base_url or "").rstrip("/")
        self.timeout = timeout

    def post_events(self, events: list[dict], device_token: str) -> list[dict]:
        if not self.base_url:
            raise TransportError("sync endpoint is not configured; running offline")
        body = json.dumps({"events": events}).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}/api/v1/sync/events/",
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Device {device_token}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))["acknowledgements"]
        except urllib.error.HTTPError as exc:
            raise TransportError(f"sync endpoint rejected request: HTTP {exc.code}")
        except urllib.error.URLError as exc:
            raise TransportError(f"connection failure: {exc.reason}")

    def check_connectivity(self) -> bool:
        if not self.base_url:
            return False
        try:
            request = urllib.request.Request(f"{self.base_url}/api/v1/health/", method="HEAD")
            urllib.request.urlopen(request, timeout=self.timeout)
            return True
        except (urllib.error.URLError, OSError):
            return False
