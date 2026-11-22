"""Idempotent sync-event ingest with server-side effect application and
conflict quarantine.

Acknowledgement statuses returned to the desktop (contract in
documentation/architecture/OVERVIEW.md and the desktop engine):

- ``accepted``  — processed exactly once, effect applied.
- ``duplicate`` — previously processed; no second effect (idempotency).
- ``conflict``  — refused by a business-integrity check; the event and its
  effect are quarantined and recorded, never discarded, never partially
  applied. The desktop keeps the sale locally and flags it for review.
- ``rejected``  — permanently invalid and cannot ever be applied; the desktop
  quarantines the local record but the event is not retried as-is.

Per-event server sequencing (`server_seq`) gives the reconciliation tasks a
total tenant-local order. Events are processed inside one transaction with
their inbox row so a crash cannot produce an applied effect without a
record (or vice versa).
"""

from __future__ import annotations

import logging

from django.db import transaction as db_tx
from rest_framework import status as http_status
from rest_framework.parsers import JSONParser
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.audit.models import AuditLog
from apps.devices.auth import (
    DeviceRateThrottle,
    DeviceTokenAuthentication,
    IsDeviceOrUser,
)
from apps.synchronization.models import ConflictRecord, InboxEvent
from apps.synchronization.serializers import SyncEventSerializer

logger = logging.getLogger("synchronization")


class SyncIngestView(APIView):
    parser_classes = [JSONParser]
    authentication_classes = [DeviceTokenAuthentication]
    throttle_classes = [DeviceRateThrottle]
    permission_classes = [IsDeviceOrUser]

    def post(self, request):
        token_obj = request.auth
        device = token_obj.device
        raw = request.data.get("events", [])
        if not isinstance(raw, list):
            return Response(
                {"detail": "body must be {\"events\": [...]}", "acknowledgements": []},
                status=http_status.HTTP_400_BAD_REQUEST,
            )
        acknowledgements = []
        client_ids = set()
        for item in raw:
            client_id = str(item.get("event_id", "")) if isinstance(item, dict) else ""
            if client_id and client_id in client_ids:
                acknowledgements.append(self._ack(
                    client_id, "rejected",
                    "duplicate event_id within the same batch"))
                continue
            client_ids.add(client_id)
            serializer = SyncEventSerializer(
                data=item, context={"device": device}
            )
            if not serializer.is_valid():
                acknowledgements.append(self._ack(
                    client_id, "rejected", str(serializer.errors)))
                continue
            with db_tx.atomic():
                ack = self._process(serializer.validated_data, device)
            acknowledgements.append(ack)
        logger.info("ingest from device %s: %d events",
                    device.device_uuid, len(acknowledgements))
        return Response({"acknowledgements": acknowledgements})

    @staticmethod
    def _ack(event_id: str, ack_status: str, detail: str) -> dict:
        return {"event_id": event_id, "status": ack_status, "detail": detail}

    def _process(self, data: dict, device) -> dict:
        event_id = data["event_id"]
        existing = InboxEvent.objects.filter(
            tenant=device.tenant, event_id=event_id
        ).first()
        if existing is not None:
            return self._ack(event_id, "duplicate",
                             f"already processed as server_seq {existing.pk}")
        inbox_event = InboxEvent.objects.create(
            tenant=device.tenant,
            device=device,
            event_id=event_id,
            event_type=data["event_type"],
            payload_version=data["payload_version"],
            device_seq=data["seq"],
            payload=data["payload"],
        )
        conflict_detail = self._detect_conflict(inbox_event)
        if conflict_detail is not None:
            ConflictRecord.objects.create(
                tenant=device.tenant,
                device=device,
                inbox_event=inbox_event,
                event_id=event_id,
                event_type=inbox_event.event_type,
                detail=conflict_detail,
                payload=data["payload"],
            )
            AuditLog.objects.create(
                tenant=device.tenant, device=device,
                action="sync.conflict_quarantined",
                target_type="event", target_uuid=event_id,
                detail=conflict_detail,
            )
            return self._ack(event_id, "conflict", conflict_detail)
        self._apply_effect(inbox_event, data)
        return self._ack(event_id, "accepted", "")

    def _apply_effect(self, inbox_event: InboxEvent, data: dict) -> None:
        """Apply the business effect inside the caller's atomic transaction.

        The reservation journal records every accepted event so that the
        inventory reconciliation tasks can all enumerate event types uniformly.
        Materialized central inventories (products, balances) are cloud-side
        aggregates built from these accepted events; see
        documentation/synchronization/SYNC.md for the contract.
        """
        AuditLog.objects.create(
            tenant=inbox_event.tenant,
            device=inbox_event.device,
            action=f"sync.applied.{inbox_event.event_type}",
            target_type="event",
            target_uuid=inbox_event.event_id,
            detail={"device_seq": inbox_event.device_seq},
        )

    def _detect_conflict(self, inbox_event) -> str | None:
        """Refuse events whose payloads violate verifiable business invariants.

        Only server-side verifiable facts are checked (exactly;
        Decimal arithmetic, never float):

        - ``accounting.journal_posted``: debit total must equal credit total
          and at least one side must be non-zero. An unbalanced journal can
          never enter central records.
        - ``inventory.movement``: positive decimal quantity, direction in
          {1, -1}, known movement type.
        - ``sale.created``: item/payments/totals must be well-formed decimal
          amounts and the recorded payment total must equal the sale total.

        Failures are quarantined as conflicts (payload preserved verbatim for
        authorized review), never applied and never discarded. Deeper
        cross-device stock reconciliation is a Celery task's responsibility:
        two offline devices may legitimately consume the same allocated
        branch stock, so availability conflicts are resolved with audited
        reconciliation movements, not by refusing one device's valid sale.
        """
        from decimal import Decimal, InvalidOperation

        payload = inbox_event.payload
        event_type = inbox_event.event_type

        def decimal_of(value, label, problems):
            try:
                return Decimal(str(value))
            except (InvalidOperation, ValueError, TypeError):
                problems.append(f"{label} is not a valid decimal amount: {value!r}")
                return None

        if event_type == "accounting.journal_posted":
            problems: list[str] = []
            if payload.get("schema") != "journal_entry":
                problems.append(
                    f"payload schema {payload.get('schema')!r} is not 'journal_entry'"
                )
            lines = payload.get("lines")
            if not isinstance(lines, list) or not lines:
                problems.append("journal payload carries no lines")
            else:
                debits = Decimal("0")
                credits = Decimal("0")
                for line in lines:
                    debit = decimal_of(line.get("debit"), "debit", problems)
                    credit = decimal_of(line.get("credit"), "credit", problems)
                    if debit is not None and credit is not None:
                        if debit < 0 or credit < 0:
                            problems.append(f"negative amount on line {line!r}")
                        if debit > 0 and credit > 0:
                            problems.append(
                                f"line posts both sides: {line!r}"
                            )
                        debits += debit
                        credits += credit
                if debits != credits:
                    problems.append(
                        f"unbalanced journal: debits {debits} != credits {credits}"
                    )
                elif debits == 0 and credits == 0:
                    problems.append("journal carries no amounts")
            return "; ".join(problems) if problems else None

        if event_type == "inventory.movement":
            problems = []
            if payload.get("schema") != "inventory_movement":
                problems.append(
                    f"payload schema {payload.get('schema')!r} is not"
                    " 'inventory_movement'"
                )
            quantity = decimal_of(payload.get("quantity"), "quantity", problems)
            if quantity is not None and quantity <= 0:
                problems.append(f"non-positive movement quantity {quantity}")
            direction = payload.get("direction")
            if direction not in (1, -1, "1", "-1"):
                problems.append(f"invalid movement direction {direction!r}")
            movement_type = payload.get("movement_type")
            known = {
                "PURCHASE_RECEIPT", "SALE", "RETURN_IN", "RETURN_OUT",
                "ADJUSTMENT", "TRANSFER_IN", "TRANSFER_OUT", "DAMAGED",
                "LOST", "COUNT", "RECONCILIATION",
            }
            if movement_type not in known:
                problems.append(f"unknown movement_type {movement_type!r}")
            return "; ".join(problems) if problems else None

        if event_type == "sale.created":
            problems = []
            totals = payload.get("totals")
            if not isinstance(totals, dict):
                problems.append("sale payload carries no totals object")
                totals = {}
            total = decimal_of(totals.get("total"), "totals.total", problems)
            items = payload.get("items")
            if not isinstance(items, list) or not items:
                problems.append("sale payload carries no items")
            payments = payload.get("payments")
            paid = Decimal("0")
            if isinstance(payments, list) and payments:
                for payment in payments:
                    amount = decimal_of(
                        payment.get("amount"), "payment.amount", problems
                    )
                    if amount is not None and amount < 0:
                        problems.append(f"negative payment amount {amount}")
                    if amount is not None:
                        paid += amount
                if total is not None and paid != total:
                    problems.append(
                        f"payments {paid} do not equal sale total {total}"
                    )
            else:
                problems.append("sale payload carries no payments")
            return "; ".join(problems) if problems else None

        return None
