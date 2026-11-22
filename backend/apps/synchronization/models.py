"""Server-side inbox for device-originated sync events.

Events arrive exclusively over authenticated device channels; the tenant is
always resolved from the authenticated device, never from the payload.
Processing is idempotent: an event_id already present in a tenant's inbox
returns `duplicate` and applies no second business effect.
"""

from __future__ import annotations

from django.db import models

from apps.devices.models import Device
from apps.tenants.models import BaseModel, Tenant


class InboxEvent(BaseModel):
    class EventType(models.TextChoices):
        SALE_CREATED = "sale.created"
        INVENTORY_MOVEMENT = "inventory.movement"
        JOURNAL_POSTED = "accounting.journal_posted"

    tenant = models.ForeignKey(Tenant, on_delete=models.PROTECT, related_name="inbox_events")
    device = models.ForeignKey(Device, on_delete=models.PROTECT, related_name="inbox_events")
    event_id = models.CharField(max_length=32)
    event_type = models.CharField(max_length=64, choices=EventType.choices)
    payload_version = models.PositiveIntegerField(default=1)
    device_seq = models.BigIntegerField()
    payload = models.JSONField()
    acknowledged_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("tenant", "event_id"), name="uniq_inbox_event_per_tenant"
            )
        ]
        indexes = [
            models.Index(fields=["tenant", "device", "device_seq"]),
        ]


class ConflictRecord(BaseModel):
    """A delivered event whose business effect was refused by validation.

    The original payload is preserved verbatim for audited manual resolution;
    nothing is discarded and no partial effect is applied.
    """

    class Status(models.TextChoices):
        OPEN = "OPEN"
        RESOLVED = "RESOLVED"

    tenant = models.ForeignKey(Tenant, on_delete=models.PROTECT, related_name="conflicts")
    device = models.ForeignKey(Device, on_delete=models.PROTECT, related_name="conflicts")
    inbox_event = models.ForeignKey(
        InboxEvent, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="conflicts",
    )
    event_id = models.CharField(max_length=32)
    event_type = models.CharField(max_length=64)
    detail = models.TextField()
    payload = models.JSONField()
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.OPEN)
    resolution = models.TextField(blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
