"""Background synchronization engine.

Drains the transactional outbox in batches with idempotent resubmission,
exponential backoff, and acknowledgement tracking. Designed to run in its
own thread (the Qt worker owns it) — it never calls UI code and never holds
long-lived transactions. Failed events are retried forever (they cannot be
discarded); conflicts go into the local exception queue.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone

from ..database.db import Database
from .outbox import Outbox
from .transport import SyncTransport, TransportError


class SyncEngine:
    def __init__(self, db: Database, transport: SyncTransport, device_token_getter=None,
                 batch_size: int = 50):
        self.db = db
        self.transport = transport
        self.device_token_getter = device_token_getter or (lambda: None)
        self.batch_size = batch_size
        self.outbox = Outbox(db)
        self._stop = threading.Event()

    def stop(self) -> None:
        self._stop.set()

    def run_once(self) -> dict:
        """One drain cycle: submit pending events in seq order and apply acks."""
        batch = self.outbox.pending_batch(limit=self.batch_size)
        if not batch:
            return {"submitted": 0, "acknowledged": 0, "conflicts": 0, "retries": 0}
        envelope = [self._envelope(row) for row in batch]
        try:
            token = self.device_token_getter() or ""
            acknowledgements = self.transport.post_events(envelope, token)
        except TransportError as exc:
            for row in batch:
                self._retry(row, str(exc))
            return {
                "submitted": 0,
                "acknowledged": 0,
                "conflicts": 0,
                "retries": len(batch),
                "error": str(exc),
            }
        results = {"submitted": len(batch), "acknowledged": 0, "conflicts": 0, "retries": 0}
        ack_by_id = {a["event_id"]: a for a in acknowledgements}
        with self.db.transaction() as db:
            for row in batch:
                event_id = row["event_id"]
                ack = ack_by_id.get(event_id)
                if ack is None:
                    self.outbox.schedule_retry(
                        event_id, row["attempts"] + 1, "missing acknowledgement"
                    )
                    results["retries"] += 1
                elif ack["status"] == "accepted":
                    self.outbox.mark_acknowledged(event_id)
                    results["acknowledged"] += 1
                elif ack["status"] == "duplicate":
                    self.outbox.mark_acknowledged(event_id)
                    results["acknowledged"] += 1
                elif ack["status"] == "conflict":
                    payload = json.loads(row["payload"])
                    self.outbox.mark_conflict(event_id, ack.get("detail", ""), payload)
                    results["conflicts"] += 1
                elif ack["status"] == "rejected":
                    self.outbox.mark_rejected(event_id, ack.get("detail", "invalid"))
                    results["retries"] += 1
                else:
                    self.outbox.schedule_retry(
                        event_id, row["attempts"] + 1,
                        f"unknown ack status {ack.get('status')!r}",
                    )
                    results["retries"] += 1
            db.execute(
                "INSERT OR IGNORE INTO sync_checkpoints (id) VALUES (1)"
            )
            db.execute(
                "UPDATE sync_checkpoints SET last_sync_at=?,"
                " last_successful_sync_at=CASE WHEN ? THEN ? ELSE last_successful_sync_at END"
                " WHERE id=1",
                (self._now_iso(), results["retries"] == 0, self._now_iso()),
            )
            self.outbox.log("INFO", f"sync cycle: {json.dumps(results)}")
        return results

    def replayed_run_until_done(self, max_cycles: int = 100) -> dict:
        totals = {"submitted": 0, "acknowledged": 0, "conflicts": 0, "retries": 0}
        for _ in range(max_cycles):
            result = self.run_once()
            for key in totals:
                totals[key] += result.get(key, 0)
            if result.get("submitted", 0) == 0:
                break
        return totals

    @staticmethod
    def _envelope(row: dict) -> dict:
        return {
            "event_id": row["event_id"],
            "tenant_id": row["tenant_id"],
            "device_id": row["device_id"],
            "event_type": row["event_type"],
            "payload_version": row["payload_version"],
            "seq": row["seq"],
            "created_at": row["created_at"],
            "payload": json.loads(row["payload"]),
        }

    def _retry(self, row: dict, error: str) -> None:
        with self.db.transaction() as db:
            self.outbox.schedule_retry(row["event_id"], row["attempts"] + 1, error)
            self.outbox.log("WARN", f"retry scheduled: {error}", row["event_id"])

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat(timespec="seconds")
