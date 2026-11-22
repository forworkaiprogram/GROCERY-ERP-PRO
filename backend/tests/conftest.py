"""Backend test suite fixtures.

Proves against the real desktop verification code (imports from desktop/)
that the signed artifacts this server mints satisfy the EXE's verifiers.
"""

import sys
import uuid as uuidlib
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

PROJECT_ROOT = Path(__file__).resolve().parents[2]
for candidate in (str(PROJECT_ROOT), str(PROJECT_ROOT / "desktop")):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

from apps.accounts.models import Membership  # noqa: E402
from apps.devices.models import Device, DeviceToken  # noqa: E402
from apps.subscriptions.models import Plan, Subscription  # noqa: E402
from apps.tenants.models import Tenant  # noqa: E402
from django.conf import settings  # noqa: E402
from django.utils import timezone  # noqa: E402


def make_signing_key_pair(tmp_path, name: str):
    """Returns (private_pem_path, public_pem_path) Ed25519 key pair."""
    private_key = Ed25519PrivateKey.generate()
    private_pem = private_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    public_pem = private_key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    private_path = tmp_path / f"{name}_private.pem"
    public_path = tmp_path / f"{name}_public.pem"
    private_path.write_bytes(private_pem)
    public_path.write_bytes(public_pem)
    return private_path, public_path


@pytest.fixture()
def signing_keys(tmp_path):
    update_priv, update_pub = make_signing_key_pair(tmp_path, "update")
    ent_priv, ent_pub = make_signing_key_pair(tmp_path, "entitlement")
    with __import__("django.test", fromlist=["override_settings"]).override_settings(
        UPDATE_SIGNING_KEY_PATH=str(update_priv),
        ENTITLEMENT_SIGNING_KEY_PATH=str(ent_priv),
    ):
        yield {"update": (update_priv, update_pub),
               "entitlement": (ent_priv, ent_pub)}


def make_user(username: str, password: str):
    from django.contrib.auth import get_user_model

    User = get_user_model()
    return User.objects.create_user(username=username, password=password)


def make_tenant_with_user(role: str = Membership.Role.OWNER):
    tenant = Tenant.objects.create(name=f"Business {uuidlib.uuid4().hex[:8]}",
                                   slug=uuidlib.uuid4().hex[:12])
    user = make_user(f"user_{uuidlib.uuid4().hex[:10]}", "S3cure-passphrase!")
    Membership.objects.create(tenant=tenant, user=user, role=role)
    return tenant, user


def enroll_device(client, user, tenant) -> tuple[Device, str]:
    client.force_authenticate(user=user)
    response = client.post(
        "/api/v1/devices/enroll/",
        {"tenant_uuid": str(tenant.uuid), "name": "POS-1"},
        content_type="application/json",
    )
    assert response.status_code == 201, response.content
    body = response.json()
    client.force_authenticate(user=None)
    device = Device.objects.get(device_uuid=uuidlib.UUID(body["device_uuid"]))
    return device, body["token"]


def make_subscription(tenant, plan: Plan, status=Subscription.Status.ACTIVE,
                      period_days=30) -> Subscription:
    return Subscription.objects.create(
        tenant=tenant,
        plan=plan,
        status=status,
        current_period_end=timezone.now() + __import__("datetime").timedelta(days=period_days),
    )


def make_plan(code="pro", **entitlements) -> Plan:
    return Plan.objects.create(
        code=code, name=code.title(), price_yer="25000",
        entitlements={"max_branches": 3, "max_users": 10, "max_devices": 5,
                      "accounting": True, **entitlements},
    )
