"""Transactional Outbox. Events are appended inside the SAME SQLite
transaction as the business data they describe (mandatory invariant #2).
"""

from __future__ import annotations

import json
import uuid as uuidlib
from datetime import datetime, timedelta, timezone

EVENT_TYPES = frozenset(
    {
        "sale.created",
        "sale.payment",
        "sale.returned",
        "inventory.movement",
        "inventory.adjustment",
        "accounting.journal_posted",
        "customer.payment",
        "supplier.payment",
        "purchase.received",
        "expense.created",
        "cash.session_closed",
    }
)


class OutboxError(ValueError):
    pass


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Outbox:
    def __init__(self, db):
        self.db = db

    def next_seq(self, device_id: str) -> int:
        row = self.db.query_one(
            "SELECT COALESCE(MAX(seq), 0) AS s FROM outbox_events WHERE device_id=?",
            (device_id,),
        )
        return int(row["s"]) + 1

    def append(
        self,
        *,
        tenant_id: str,
        device_id: str,
        event_type: str,
        payload: dict,
        references_sale: str | None = None,
    ) -> dict:
        """Append an event. Caller must hold an open transaction."""
        if event_type not in EVENT_TYPES:
            raise OutboxError(f"unknown event type {event_type!r}")
        event_id = str(uuidlib.uuid4())
        seq = self.next_seq(device_id)
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        self.db.execute(
            "INSERT INTO outbox_events (event_id, tenant_id, device_id, event_type,"
            " payload_version, seq, payload, references_sale, state)"
            " VALUES (?,?,?,?,?,?,?,?, 'PENDING')",
            (
                event_id.replace("-", ""),
                tenant_id,
                device_id,
                event_type,
                int(payload.get("version", 1)),
                seq,
                canonical,
                references_sale,
            ),
        )
        return {"event_id": event_id, "seq": seq}

    def pending_batch(self, limit: int = 100) -> list[dict]:
        rows = self.db.query_all(
            "SELECT * FROM outbox_events WHERE state='PENDING'"
            " AND (next_attempt_at IS NULL OR next_attempt_at <= ?)"
            " ORDER BY seq LIMIT ?",
            (_now_iso(), limit),
        )
        return [dict(r) for r in rows]

    def counts(self) -> dict:
        rows = self.db.query_all(
            "SELECT state, COUNT(*) AS n FROM outbox_events GROUP BY state"
        )
        return {r["state"]: int(r["n"]) for r in rows}

    def mark_sent(self, event_id: str) -> None:
        self.db.execute(
            "UPDATE outbox_events SET state='SENT', attempts=attempts+1,"
            " next_attempt_at=NULL WHERE event_id=? AND state='PENDING'",
            (event_id,),
        )

    def mark_acknowledged(self, event_id: str) -> None:
        self.db.execute(
            "UPDATE outbox_events SET state='ACKNOWLEDGED', acknowledged_at=?,"
            " next_attempt_at=NULL WHERE event_id=?",
            (_now_iso(), event_id),
        )
        self.db.execute(
            "UPDATE sales SET sync_state='ACKNOWLEDGED' WHERE sync_state='PENDING'"
            " AND uuid IN (SELECT references_sale FROM outbox_events WHERE event_id=?)",
            (event_id,),
        )

    def mark_conflict(self, event_id: str, detail: str, payload: dict,
                      event_type: str | None = None) -> None:
        row = self.db.query_one(
            "SELECT event_type FROM outbox_events WHERE event_id=?", (event_id,)
        )
        self.db.execute(
            "INSERT OR IGNORE INTO sync_conflicts (event_id, event_type, detail, payload)"
            " VALUES (?,?,?,?)",
            (event_id, event_type or (row["event_type"] if row else ""),
             detail, json.dumps(payload, sort_keys=True)),
        )
        self.db.execute(
            "UPDATE outbox_events SET state='CONFLICT', last_error=? WHERE event_id=?",
            (detail, event_id),
        )
        self.db.execute(
            "UPDATE sales SET sync_state='CONFLICT' WHERE sync_state IN ('PENDING','SENT')"
            " AND uuid IN (SELECT references_sale FROM outbox_events WHERE event_id=?)",
            (event_id,),
        )

    def mark_rejected(self, event_id: str, detail: str) -> None:
        self.db.execute(
            "UPDATE outbox_events SET state='REJECTED', last_error=? WHERE event_id=?",
            (detail, event_id),
        )
        self.db.execute(
            "UPDATE sales SET sync_state='REJECTED' WHERE sync_state='PENDING'"
            " AND uuid IN (SELECT references_sale FROM outbox_events WHERE event_id=?)",
            (event_id,),
        )

    def schedule_retry(self, event_id: str, attempts: int, error: str) -> None:
        backoff_seconds = min(2 ** min(attempts, 6) * 5, 3600)
        next_at = (datetime.now(timezone.utc) + timedelta(seconds=backoff_seconds)).isoformat(
            timespec="seconds"
        )
        self.db.execute(
            "UPDATE outbox_events SET attempts=?, next_attempt_at=?, last_error=?,"
            " state='PENDING' WHERE event_id=? AND state <> 'CONFLICT'",
            (attempts, next_at, error, event_id.replace("-", "")),
        )

    def log(self, level: str, message: str, event_id: str | None = None) -> None:
        self.db.execute(
            "INSERT INTO sync_logs (level, message, event_id) VALUES (?,?,?)",
            (level, message, event_id),
        )
