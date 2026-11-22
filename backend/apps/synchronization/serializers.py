"""Validation of inbound sync envelopes.

The tenant and device are taken from the authenticated device token. Any
client-claimed tenant_id or device_id that disagrees with the authenticated
device is a hard validation error — never a lookup fallback.
"""

from __future__ import annotations

import re

from rest_framework import serializers

EVENT_ID_RE = re.compile(r"^[0-9a-f]{32}$")
KNOWN_EVENT_TYPES = frozenset(
    {"sale.created", "inventory.movement", "accounting.journal_posted"}
)


class SyncEventSerializer(serializers.Serializer):
    event_id = serializers.RegexField(EVENT_ID_RE)
    tenant_id = serializers.CharField()
    device_id = serializers.CharField()
    event_type = serializers.ChoiceField(choices=sorted(KNOWN_EVENT_TYPES))
    payload_version = serializers.IntegerField(min_value=1)
    seq = serializers.IntegerField(min_value=0)
    created_at = serializers.CharField()
    payload = serializers.DictField(allow_empty=True)

    def validate_tenant_id(self, value: str) -> str:
        device = self.context["device"]
        expected = str(device.tenant.uuid)
        if value != expected:
            raise serializers.ValidationError(
                "tenant_id does not match the authenticated device's tenant"
            )
        return value

    def validate_device_id(self, value: str) -> str:
        device = self.context["device"]
        expected = str(device.device_uuid)
        if value != expected:
            raise serializers.ValidationError(
                "device_id does not match the authenticated device"
            )
        return value

    def validate_payload(self, value: dict) -> dict:
        # Density cap protects the ingest API from unbounded payloads.
        if len(repr(value)) > 1_000_000:
            raise serializers.ValidationError("payload too large")
        return value
