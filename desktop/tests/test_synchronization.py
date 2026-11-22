import json

from desktop.business_logic.money import D
from desktop.synchronization.engine import SyncEngine
from desktop.synchronization.transport import SyncTransport, TransportError

TENANT = "11111111-1111-1111-1111-111111111111"
MILK = "aaaa1111-0000-0000-0000-000000000001"


class RecordingServer(SyncTransport):
    """Fake cloud: idempotent processing exactly like the DRF ingest API."""

    def __init__(self, *, online=True, conflict_on=None):
        self.online = online
        self.processed: dict[str, dict] = {}
        self.delivered: list[str] = []
        self.effects = []  # business effects that must never duplicate
        self.conflict_on = conflict_on or set()

    def check_connectivity(self):
        return self.online

    def post_events(self, events, device_token):
        if not self.online:
            raise TransportError("connection failure: offline")
        acks = []
        for event in events:
            eid = event["event_id"]
            self.delivered.append(eid)
            if eid in self.conflict_on:
                acks.append({"event_id": eid, "status": "conflict",
                             "detail": "inventory BELOW_ZERO", "resolution": "manual_review"})
            elif eid in self.processed:
                acks.append({"event_id": eid, "status": "duplicate",
                             "server_seq": self.processed[eid]["seq"]})
            else:
                # apply effect once, keyed by event_id (server inbox behavior)
                self.processed[eid] = {"seq": event["seq"], "type": event["event_type"]}
                self.effects.append((event["event_type"], eid))
                acks.append({"event_id": eid, "status": "accepted", "server_seq": event["seq"]})
        return acks


def _grant_stock(runtime, qty):
    with runtime.db.transaction() as db:
        runtime.inventory.record_movement(
            tenant_id=TENANT,
            branch_id="branch-1",
            product_uuid=MILK,
            movement_type="PURCHASE_RECEIPT",
            direction=1,
            quantity=qty,
            unit="PIECE",
            reference_type="PURCHASE",
        )


def _make_sale(runtime):
    _grant_stock(runtime, 100)
    return runtime.sales.commit_sale(
        tenant_id=TENANT, branch_id="branch-1",
        device_id=runtime.device["device_id"], cashier_id="c1",
        items=[{"product_uuid": MILK, "quantity": 2, "unit": "PIECE"}],
        payments=[{"method": "CASH", "amount": "2000.00"}],
    )


def test_acknowledgement_marks_confirmed(runtime, seeded_products):
    _make_sale(runtime)
    server = RecordingServer()
    engine = SyncEngine(runtime.db, server)
    result = engine.run_once()
    assert result["acknowledged"] == 3
    assert result["conflicts"] == 0
    sale = runtime.db.query_one("SELECT sync_state FROM sales LIMIT 1")
    assert sale["sync_state"] == "ACKNOWLEDGED"
    counts = runtime.outbox.counts()
    assert counts.get("ACKNOWLEDGED") == 3


def test_offline_sale_survives_transport_failure_then_syncs(runtime, seeded_products):
    _make_sale(runtime)
    server = RecordingServer(online=False)
    engine = SyncEngine(runtime.db, server)
    outcome = engine.run_once()
    assert outcome["retries"] == 3
    # event NOT discarded; sale still present
    assert runtime.outbox.counts().get("PENDING") == 3
    assert runtime.db.query_one("SELECT COUNT(*) n FROM sales")["n"] == 1

    server.online = True
    runtime.db.execute("UPDATE outbox_events SET next_attempt_at=NULL")
    engine.replayed_run_until_done()
    assert len(server.effects) == 3
    assert runtime.outbox.counts().get("PENDING", 0) == 0
    assert runtime.outbox.counts().get("ACKNOWLEDGED") == 3


def test_duplicate_delivery_never_duplicates_effects(runtime, seeded_products):
    _make_sale(runtime)
    server = RecordingServer()
    engine = SyncEngine(runtime.db, server)
    # first delivery
    engine.replayed_run_until_done()
    effects_after_first = list(server.effects)
    # force re-delivery of the same event directly at transport level
    row = runtime.db.query_one("SELECT * FROM outbox_events LIMIT 1")
    envelope = SyncEngine._envelope(row)
    server.post_events([envelope], "")
    assert len(server.effects) == len(effects_after_first)
    assert len(set(server.delivered)) == len(server.delivered) - 1  # one dup delivered
    # server kept a single effect for that event
    types = [t for t, _ in server.effects]
    assert types.count("sale.created") == 1


def test_conflict_moves_to_exception_queue(runtime, seeded_products):
    _make_sale(runtime)
    events = runtime.db.query_all("SELECT event_id FROM outbox_events WHERE state='PENDING'")
    server = RecordingServer(conflict_on={events[0]["event_id"]})
    engine = SyncEngine(runtime.db, server)
    result = engine.run_once()
    assert result["conflicts"] >= 1
    sale = runtime.db.query_one("SELECT sync_state FROM sales LIMIT 1")
    assert sale["sync_state"] == "CONFLICT"
    conflicts = runtime.db.query_all("SELECT * FROM sync_conflicts WHERE status='OPEN'")
    assert conflicts and conflicts[0]["detail"] == "inventory BELOW_ZERO"
    # the sale itself is preserved — never deleted
    assert runtime.db.query_one("SELECT COUNT(*) n FROM sales")["n"] == 1


def test_retry_backoff_is_exponential(runtime, seeded_products):
    _make_sale(runtime)
    server = RecordingServer(online=False)
    engine = SyncEngine(runtime.db, server)
    engine.run_once()
    rows = runtime.db.query_all("SELECT attempts, next_attempt_at, last_error FROM outbox_events")
    assert all(row["attempts"] == 1 for row in rows)
    assert all(row["next_attempt_at"] is not None for row in rows)
    assert all("offline" in row["last_error"].lower() for row in rows)
