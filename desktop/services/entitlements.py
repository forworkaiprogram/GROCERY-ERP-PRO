"""Signed subscription entitlement snapshots (offline authority).

The server signs an entitlement snapshot (canonical JSON) with its Ed25519
key. The desktop verifies the signature before caching, and enforces:
- snapshot expiry (valid_until) + a configurable offline grace period,
- downgrade to a strictly LIMITED offline feature set only after expiry
  (never deletion of data, never premium unlocks).
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from ..security.cloud_signing import Ed25519PublicKey, verify_signature

OFFLINE_LITE_ENTITLEMENTS = {
    "pos": True,
    "products": True,
    "inventory": True,
    "sales_history": True,
    "sync": True,
    "advanced_reports": False,
    "accounting": False,
    "payroll": False,
    "hr": False,
}


class EntitlementError(ValueError):
    pass


def canonical(bytes_or_dict) -> bytes:
    if isinstance(bytes_or_dict, bytes):
        return bytes_or_dict
    return json.dumps(bytes_or_dict, sort_keys=True, separators=(",", ":")).encode()


def verify_snapshot(signed: dict, public_key: Ed25519PublicKey) -> dict:
    """signed: {payload: {...}, signature: b64} — raises on any failure."""
    payload = signed.get("payload")
    signature = signed.get("signature")
    if payload is None or signature is None:
        raise EntitlementError("malformed entitlement snapshot")
    if not verify_signature(canonical(payload), signature, public_key):
        raise EntitlementError("entitlement snapshot signature invalid")
    valid_until = datetime.fromisoformat(payload["valid_until"].replace("Z", "+00:00"))
    if valid_until.tzinfo is None:
        valid_until = valid_until.replace(tzinfo=timezone.utc)
    payload["_valid_until_dt"] = valid_until
    return payload


class EntitlementService:
    def __init__(self, db, public_key: Ed25519PublicKey, grace_hours: int = 72):
        self.db = db
        self.public_key = public_key
        self.grace_hours = grace_hours

    def cache_snapshot(self, signed: dict) -> dict:
        payload = verify_snapshot(signed, self.public_key)
        self.db.execute(
            "INSERT INTO entitlement_cache (id, plan, entitlements, signature,"
            " signed_at, valid_until, verified) VALUES (1,?,?,?,?,?,1)"
            " ON CONFLICT(id) DO UPDATE SET plan=excluded.plan,"
            " entitlements=excluded.entitlements, signature=excluded.signature,"
            " signed_at=excluded.signed_at, valid_until=excluded.valid_until,"
            " verified=1",
            (
                payload["plan"],
                json.dumps(payload["entitlements"], sort_keys=True),
                signed["signature"],
                payload["signed_at"],
                payload["valid_until"],
            ),
        )
        return payload

    def current(self, now: datetime | None = None) -> dict:
        """Effective entitlements.

        - Verified, unexpired snapshot -> full cached entitlements.
        - Expired within grace period -> snapshot flags ANDed with the lite
          offline set (premium features off, core selling on).
        - No verified snapshot -> lite set only.
        """
        now = now or datetime.now(timezone.utc)
        row = self.db.query_one("SELECT * FROM entitlement_cache WHERE id=1")
        if row is None or not row["verified"]:
            return dict(OFFLINE_LITE_ENTITLEMENTS)
        entitlements = dict(json.loads(row["entitlements"]))
        valid_until = datetime.fromisoformat(row["valid_until"].replace("Z", "+00:00"))
        if valid_until.tzinfo is None:
            valid_until = valid_until.replace(tzinfo=timezone.utc)
        if now <= valid_until:
            return entitlements
        grace_end = valid_until + timedelta(hours=self.grace_hours)
        if now <= grace_end:
            limited = dict(OFFLINE_LITE_ENTITLEMENTS)
            for key, value in entitlements.items():
                if key in limited:
                    limited[key] = limited[key] and bool(value)
            return limited
        return dict(OFFLINE_LITE_ENTITLEMENTS)

    def is_expired_beyond_grace(self, now: datetime | None = None) -> bool:
        now = now or datetime.now(timezone.utc)
        row = self.db.query_one("SELECT valid_until, verified FROM entitlement_cache WHERE id=1")
        if row is None or not row["verified"]:
            return False
        valid_until = datetime.fromisoformat(row["valid_until"].replace("Z", "+00:00"))
        if valid_until.tzinfo is None:
            valid_until = valid_until.replace(tzinfo=timezone.utc)
        return now > valid_until + timedelta(hours=self.grace_hours)
