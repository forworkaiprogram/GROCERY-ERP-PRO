# Synchronization guide

## Event contract (v1)

Each outbox event is submitted as:

```json
{
  "event_id": "32-hex uuid4 without dashes",
  "tenant_id": "<tenant uuid>",
  "device_id": "<device uuid>",
  "event_type": "sale.created | inventory.movement | accounting.journal_posted",
  "payload_version": 1,
  "seq": <int, monotonic per device>,
  "created_at": "<iso8601>",
  "payload": { ... }
}
```

Submitted in batches to `POST /api/v1/sync/events/` with header
`Authorization: Device <token>`. Response:

```json
{"acknowledgements": [{"event_id": "...", "status": "accepted|duplicate|conflict|rejected", "detail": "..."}]}
```

| Status | Meaning | Desktop effect |
|---|---|---|
| accepted | processed exactly once, effect applied | sale sync_state → ACKNOWLEDGED |
| duplicate | already processed; no second effect | sale → ACKNOWLEDGED |
| conflict | refused by a business-integrity check; payload quarantined on the server, sale preserved locally | sync_state → CONFLICT, exception queue |
| rejected | permanently invalid (auth/tenant/payload mismatch) | sync_state → REJECTED (never retried or discarded) |

## Server-side integrity gates (real, in `apps/synchronization/views.py`)

- `accounting.journal_posted`: Decimal-exact debit==credit, no negative
  amounts, no both-sided lines; unbalanced journals can never enter central
  records (quarantined as conflicts).
- `inventory.movement`: valid schema tag, positive decimal quantity,
  direction ∈ {1,-1}, known movement type.
- `sale.created`: decimal-exact totals; payment total must equal the sale
  total.

## Idempotency

`(tenant, event_id)` is unique at the database level
(`uniq_inbox_event_per_tenant`) plus an explicit replay check inside the
ingest transaction. Repeated delivery → `duplicate`, zero extra effects.
The event row and its effect are written in one DB transaction, so a crash
cannot split them.

## Tenant/device binding

`tenant_id` and `device_id` in the payload are validated against the
authenticated device token; mismatches are rejected. The server never
resolves tenant context from client claims.

## Multi-device inventory conflicts

Devices commit sales against device allocations (see architecture
overview §multi-device protection). Two offline devices may legitimately
consume the same allocated branch stock; the server deliberately does NOT
reject either sale. Instead, stock-consumption discrepancies are surfaced
by reconciliation reports (Celery tasks read inbox events in `server_seq`
order) and resolved through audited `RECONCILIATION` movements — never
last-write-wins, never deletion.

## Retry protocol

Failed submissions are retried with exponential backoff capped at 1 hour
(`desktop/synchronization/outbox.py`). The `next_attempt_at` gate is
included in the desktop test suite. Failed events are never deleted;
conflicts are never overwritten by later acknowledgements (guarded SQL
transitions only).
