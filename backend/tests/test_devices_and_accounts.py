"""User login, device enrollment, revocation semantics, and token refresh."""


from rest_framework.test import APIClient

from apps.devices.models import Device, DeviceToken

from .conftest import enroll_device, make_tenant_with_user
import pytest

pytestmark = pytest.mark.django_db


def test_login_returns_memberships():
    tenant, user = make_tenant_with_user()
    client = APIClient()
    response = client.post(
        "/api/v1/auth/login/",
        {"username": user.username, "password": "S3cure-passphrase!"},
        content_type="application/json",
    )
    assert response.status_code == 200, response.content
    body = response.json()
    assert body["memberships"][0]["tenant_id"] == str(tenant.uuid)


def test_login_rejects_bad_password():
    tenant, user = make_tenant_with_user()
    client = APIClient()
    response = client.post(
        "/api/v1/auth/login/",
        {"username": user.username, "password": "wrong"},
        content_type="application/json",
    )
    assert response.status_code == 401


def test_enrollment_requires_membership_in_that_tenant():
    tenant, user = make_tenant_with_user()
    stranger = make_tenant_with_user()[1]
    client = APIClient()
    client.force_authenticate(user=stranger)
    response = client.post(
        "/api/v1/devices/enroll/",
        {"tenant_uuid": str(tenant.uuid), "name": "rogue"},
        content_type="application/json",
    )
    assert response.status_code == 400
    assert Device.objects.filter(tenant=tenant).count() == 0


def test_revoked_device_tokens_stop_working():
    tenant, user = make_tenant_with_user()
    client = APIClient()
    device, token = enroll_device(client, user, tenant)

    ok = APIClient().get(
        "/api/v1/devices/whoami/", HTTP_AUTHORIZATION=f"Device {token}"
    )
    assert ok.status_code == 200

    client.force_authenticate(user=user)
    revoke = client.post(
        "/api/v1/devices/",
        {"tenant_uuid": str(tenant.uuid), "device_uuid": str(device.device_uuid)},
        content_type="application/json",
    )
    assert revoke.status_code == 200

    refused = APIClient().get("/api/v1/devices/whoami/",
                              HTTP_AUTHORIZATION=f"Device {token}")
    assert refused.status_code == 401


def test_token_refresh_revokes_old_token_and_issues_new():
    tenant, user = make_tenant_with_user()
    device, token = enroll_device(APIClient(), user, tenant)
    response = APIClient().post("/api/v1/devices/refresh-token/",
                             HTTP_AUTHORIZATION=f"Device {token}")
    assert response.status_code == 200
    new_token = response.json()["token"]
    assert new_token != token
    assert DeviceToken.objects.get(**{
        "token_hash": DeviceToken.hash_token(token)}).revoked is True
    ok = APIClient().get("/api/v1/devices/whoami/",
                         HTTP_AUTHORIZATION=f"Device {new_token}")
    assert ok.status_code == 200


def test_device_listing_is_tenant_scoped():
    tenant_a, user_a = make_tenant_with_user()
    tenant_b, user_b = make_tenant_with_user()
    enroll_device(APIClient(), user_a, tenant_a)
    device_b, _ = enroll_device(APIClient(), user_b, tenant_b)

    client = APIClient()
    client.force_authenticate(user=user_b)
    listing = client.get(f"/api/v1/devices/?tenant_uuid={tenant_b.uuid}")
    assert listing.status_code == 200
    uuids = [d["device_uuid"] for d in listing.json()]
    assert str(device_b.device_uuid) in uuids
    assert len(listing.json()) == 1
    listing_other = client.get(f"/api/v1/devices/?tenant_uuid={tenant_a.uuid}")
    assert listing_other.status_code in (400, 403)
