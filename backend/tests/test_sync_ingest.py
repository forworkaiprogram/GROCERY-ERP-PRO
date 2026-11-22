"""Sync ingest: device auth enforcement, tenant mismatch refusal, idempotent
replay, integrity conflicts. Uses the exact envelope the desktop engine sends.
"""

import uuid as uuidlib

from rest_framework.test import APIClient
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.synchronization.models import ConflictRecord, InboxEvent

from .conftest import enroll_device, make_tenant_with_user
import pytest


@pytest.fixture()
def device_and_token(django_user_model):
    tenant, user = make_tenant_with_user()
    client = APIClient()
    device, token = enroll_device(client, user, tenant)
    return tenant, device, token


def event_id() -> str:
    return uuidlib.uuid4().hex


def envelope(tenant, device, eid=None, event_type="sale.created", payload=None):
    return {
        "event_id": eid or event_id(),
        "tenant_id": str(tenant.uuid),
        "device_id": str(device.device_uuid),
        "event_type": event_type,
        "payload_version": 1,
        "seq": 1,
        "created_at": timezone.now().isoformat(),
        "payload": payload or {
            "version": 1,
            "sale_uuid": "sale-" + uuidlib.uuid4().hex,
            "totals": {"total": "5000"},
            "items": [{"product_uuid": "p1", "quantity": "2"}],
            "payments": [{"method": "CASH", "amount": "5000"}],
        },
    }


pytestmark = pytest.mark.django_db


def test_device_token_required_for_sync(device_and_token):
    client = APIClient()
    response = client.post(
        "/api/v1/sync/events/", {"events": []}, content_type="application/json"
    )
    assert response.status_code == 401


def test_unknown_device_token_rejected(device_and_token):
    client = APIClient()
    response = client.post(
        "/api/v1/sync/events/",
        {"events": []},
        content_type="application/json",
        HTTP_AUTHORIZATION="Device not-a-real-token",
    )
    assert response.status_code == 401


def test_valid_event_accepted_once(device_and_token):
    tenant, device, token = device_and_token
    client = APIClient()
    response = client.post(
        "/api/v1/sync/events/",
        {"events": [envelope(tenant, device)]},
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Device {token}",
    )
    assert response.status_code == 200, response.content
    acks = response.json()["acknowledgements"]
    assert acks[0]["status"] == "accepted"
    assert InboxEvent.objects.filter(tenant=tenant).count() == 1


def test_replay_is_idempotent_duplicate_no_second_effect(device_and_token):
    tenant, device, token = device_and_token
    client = APIClient()
    env = envelope(tenant, device)
    for expected in ("accepted", "duplicate"):
        response = client.post(
            "/api/v1/sync/events/",
            {"events": [env]},
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Device {token}",
        )
        assert response.json()["acknowledgements"][0]["status"] == expected
    assert InboxEvent.objects.filter(tenant=tenant).count() == 1
    assert (AuditLog.objects.filter(action="sync.applied.sale.created")
            .count()) == 1


def test_tenant_mismatch_is_rejected_not_trusted(device_and_token):
    tenant, device, token = device_and_token
    other_tenant, _ = make_tenant_with_user()
    env = envelope(tenant, device)
    env["tenant_id"] = str(other_tenant.uuid)
    client = APIClient()
    response = client.post(
        "/api/v1/sync/events/",
        {"events": [env]},
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Device {token}",
    )
    acks = response.json()["acknowledgements"]
    assert acks[0]["status"] == "rejected"
    assert InboxEvent.objects.count() == 0
    assert ConflictRecord.objects.count() == 0


def test_device_mismatch_is_rejected(device_and_token):
    tenant, device, token = device_and_token
    env = envelope(tenant, device)
    env["device_id"] = str(uuidlib.uuid4())
    client = APIClient()
    response = client.post(
        "/api/v1/sync/events/",
        {"events": [env]},
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Device {token}",
    )
    assert response.json()["acknowledgements"][0]["status"] == "rejected"
    assert InboxEvent.objects.count() == 0


def test_unbalanced_journal_is_conflict_not_applied(device_and_token):
    tenant, device, token = device_and_token
    payload = {
        "schema": "journal_entry",
        "uuid": "jrn-" + uuidlib.uuid4().hex,
        "lines": [
            {"account_code": "1010", "debit": "1000", "credit": "0"},
            {"account_code": "4000", "debit": "0", "credit": "900"},
        ],
    }
    client = APIClient()
    response = client.post(
        "/api/v1/sync/events/",
        {"events": [envelope(tenant, device, event_type="accounting.journal_posted",
                             payload=payload)]},
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Device {token}",
    )
    acks = response.json()["acknowledgements"]
    assert acks[0]["status"] == "conflict"
    assert "unbalanced" in acks[0]["detail"]
    conflict = ConflictRecord.objects.get(tenant=tenant)
    assert conflict.payload == payload
    assert InboxEvent.objects.count() == 1


def test_balanced_journal_accepted(device_and_token):
    tenant, device, token = device_and_token
    payload = {
        "schema": "journal_entry",
        "uuid": "jrn-" + uuidlib.uuid4().hex,
        "lines": [
            {"account_code": "1010", "debit": "1000", "credit": "0"},
            {"account_code": "4000", "debit": "0", "credit": "1000"},
        ],
    }
    client = APIClient()
    response = client.post(
        "/api/v1/sync/events/",
        {"events": [envelope(tenant, device, event_type="accounting.journal_posted",
                             payload=payload)]},
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Device {token}",
    )
    assert response.json()["acknowledgements"][0]["status"] == "accepted"
    assert ConflictRecord.objects.count() == 0


def test_sale_payment_mismatch_is_conflict(device_and_token):
    tenant, device, token = device_and_token
    payload = {
        "version": 1,
        "sale_uuid": "sale-" + uuidlib.uuid4().hex,
        "totals": {"total": "5000"},
        "items": [{"product_uuid": "p1", "quantity": "2"}],
        "payments": [{"method": "CASH", "amount": "4000"}],
    }
    client = APIClient()
    response = client.post(
        "/api/v1/sync/events/",
        {"events": [envelope(tenant, device, payload=payload)]},
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Device {token}",
    )
    acks = response.json()["acknowledgements"]
    assert acks[0]["status"] == "conflict"
    assert "do not equal" in acks[0]["detail"]


def test_tenant_isolation_between_devices(django_user_model):
    tenant_a, user_a = make_tenant_with_user()
    tenant_b, user_b = make_tenant_with_user()
    client = APIClient()
    device_a, token_a = enroll_device(client, user_a, tenant_a)
    device_b, token_b = enroll_device(client, user_b, tenant_b)
    env_b = envelope(tenant_b, device_b)
    response = client.post(
        "/api/v1/sync/events/",
        {"events": [env_b]},
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Device {token_a}",
    )
    acks = response.json()["acknowledgements"]
    assert acks[0]["status"] == "rejected"
    assert InboxEvent.objects.filter(tenant=tenant_b).count() == 0
    env_b_replayed = client.post(
        "/api/v1/sync/events/",
        {"events": [env_b]},
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Device {token_b}",
    )
    assert env_b_replayed.json()["acknowledgements"][0]["status"] == "accepted"
