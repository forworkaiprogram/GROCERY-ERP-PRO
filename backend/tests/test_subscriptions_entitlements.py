"""Entitlement snapshots: device-only issuance, signature verified by the
REAL desktop verifier, and expiry behaviour that never implies data loss.
"""

from datetime import timedelta

from rest_framework.test import APIClient
from django.utils import timezone

from apps.devices.models import Device
from apps.subscriptions.models import Subscription


from .conftest import (
    enroll_device,
    make_plan,
    make_subscription,
    make_tenant_with_user,
)
import pytest

pytestmark = pytest.mark.django_db


def snapshot_of(token: str) -> dict:
    response = APIClient().get(
        "/api/v1/subscriptions/snapshot/", HTTP_AUTHORIZATION=f"Device {token}"
    )
    return response


def test_snapshot_requires_device_authentication():
    response = APIClient().get("/api/v1/subscriptions/snapshot/")
    assert response.status_code in (401, 403)


def test_snapshot_verifies_with_desktop_verifier(signing_keys):
    tenant, user = make_tenant_with_user()
    plan = make_plan()
    make_subscription(tenant, plan, period_days=7)
    device, token = enroll_device(APIClient(), user, tenant)

    response = snapshot_of(token)
    assert response.status_code == 200, response.content
    signed = response.json()

    from desktop.services.entitlements import verify_snapshot
    from desktop.security.cloud_signing import load_public_key

    public_key = load_public_key(signing_keys["entitlement"][1].read_bytes())
    payload = verify_snapshot(signed, public_key)
    assert payload["tenant_id"] == str(tenant.uuid)
    assert payload["plan"] == plan.code
    assert payload["entitlements"]["max_devices"] == 5


def test_expired_beyond_grace_snapshot_has_no_entitlements(signing_keys):
    tenant, user = make_tenant_with_user()
    plan = make_plan(entitlements={"payroll": True})
    make_subscription(tenant, plan, status=Subscription.Status.ACTIVE,
                      period_days=-90)
    device, token = enroll_device(APIClient(), user, tenant)

    response = snapshot_of(token)
    payload = response.json()["payload"]
    assert payload["entitlements"] == {}


def test_business_data_is_never_deleted_by_subscription_expiry(signing_keys):
    """The subscription lifecycle only changes subscription rows; no
    enrollment, device, token, or tenant mutation occurs on expiry."""
    tenant, user = make_tenant_with_user()
    plan = make_plan()
    device, token = enroll_device(APIClient(), user, tenant)
    subscription = make_subscription(tenant, plan, period_days=-1)

    assert subscription.effective_status() == Subscription.Status.GRACE
    assert Device.objects.filter(tenant=tenant, status=Device.Status.ACTIVE).exists()
    assert tenant.status == "ACTIVE"
    snapshot_of(token)
    assert Device.objects.filter(tenant=tenant).count() == 1


def test_tenant_cannot_read_another_tenants_subscription(signing_keys):
    tenant_a, user_a = make_tenant_with_user()
    tenant_b, _ = make_tenant_with_user()
    plan = make_plan()
    make_subscription(tenant_b, plan)
    device, token = enroll_device(APIClient(), user_a, tenant_a)

    response = snapshot_of(token)
    assert response.status_code == 404
    assert "subscription" in response.json()["detail"]
    from apps.subscriptions.models import Subscription as Sub

    assert not Sub.objects.filter(tenant=tenant_a).exists()


def test_declare_payment_requires_membership_and_starts_pending():
    tenant, user = make_tenant_with_user()
    plan = make_plan()
    make_subscription(tenant, plan)
    client = APIClient()
    client.force_authenticate(user=user)
    response = client.post(
        "/api/v1/subscriptions/payments/declare/",
        {"tenant_uuid": str(tenant.uuid), "amount_yer": "25000",
         "method": "BANK_TRANSFER", "reference": "TR-9981"},
        content_type="application/json",
    )
    assert response.status_code == 201, response.content
    assert response.json()["status"] == "PENDING"

    stranger = make_tenant_with_user()[1]
    client.force_authenticate(user=stranger)
    refused = client.post(
        "/api/v1/subscriptions/payments/declare/",
        {"tenant_uuid": str(tenant.uuid), "amount_yer": "25000",
         "method": "CASH"},
        content_type="application/json",
    )
    assert refused.status_code == 404
