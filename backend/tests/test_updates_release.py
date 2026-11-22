"""Release publication authorization and the signed-manifest contract with
the desktop Update Center's REAL verifier (desktop/updates/manifest.py).
"""

import io
import uuid as uuidlib

from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from apps.accounts.models import Membership
from apps.updates.models import AppRelease

from .conftest import make_tenant_with_user
import pytest

pytestmark = pytest.mark.django_db


def upload_package(content: bytes, name="groceryerp-1.1.0.pkg"):
    return SimpleUploadedFile(name, content)


def publish(client, user, version="1.1.0", channel="stable", package=b"PKG-1",
            **fields):
    client.force_authenticate(user=user)
    data = {
        "version": version, "channel": channel,
        "min_schema_version": fields.get("min_schema_version", 1),
        "max_schema_version": fields.get("max_schema_version", 2),
        "release_notes": fields.get("release_notes", "notes"),
        "required": fields.get("required", True),
        "package": upload_package(package),
    }
    return client.post("/api/v1/updates/releases/publish/", data, format="multipart")


def test_tenant_admin_cannot_publish_releases():
    tenant, user = make_tenant_with_user()
    client = APIClient()
    response = publish(client, user)
    assert response.status_code == 403
    assert AppRelease.objects.count() == 0


def test_super_admin_publish_and_signed_list_matches_desktop(
        django_user_model, signing_keys, tmp_path, settings_mod=None):
    tenant, admin = make_tenant_with_user(role=Membership.Role.SUPER_ADMIN)
    content = b"GROCERY-ERP-PRO-UPDATE-PACKAGE-1.1.0"
    client = APIClient()
    response = publish(client, admin, package=content)
    assert response.status_code == 201, response.content
    sha = response.json()["sha256"]

    list_response = client.get("/api/v1/updates/releases/?channel=stable")
    assert list_response.status_code == 200, list_response.content
    body = list_response.json()
    assert len(body["releases"]) == 1

    from desktop.security.cloud_signing import load_public_key
    from desktop.updates.manifest import (
        check_compatibility,
        verify_manifest,
        verify_package,
    )

    public_key = load_public_key(signing_keys["update"][1].read_bytes())
    payload = verify_manifest(body["releases"][0], public_key)
    assert payload["version"] == "1.1.0"
    assert payload["sha256"] == sha
    assert payload["package_size"] == len(content)
    check_compatibility(payload, current_version="1.0.0", local_schema_version=1)
    staged = tmp_path / "pkg"
    staged.write_bytes(content)
    verify_package(staged, payload["sha256"])


@pytest.fixture()
def media_root(tmp_path, settings):
    settings.MEDIA_ROOT = tmp_path
    return tmp_path


def test_paused_release_disappears_from_distribution(django_user_model,
                                                     media_root,
                                                     signing_keys):
    tenant, admin = make_tenant_with_user(role=Membership.Role.SUPER_ADMIN)
    client = APIClient()
    created = publish(client, admin)
    release_id = created.json()["release_id"]

    manage = client.post(
        "/api/v1/updates/releases/manage/",
        {"action": "pause", "release_id": release_id},
        content_type="application/json",
    )
    assert manage.status_code == 200
    listing = client.get("/api/v1/updates/releases/?channel=stable")
    assert listing.json()["releases"] == []


def test_tenant_admin_cannot_manage_releases(media_root):
    tenant, user = make_tenant_with_user()
    client = APIClient()
    response = client.post(
        "/api/v1/updates/releases/manage/",
        {"action": "pause", "release_id": 1},
        content_type="application/json",
    )
    assert response.status_code == 403


def test_device_reports_update_attempt(media_root):
    from .conftest import enroll_device

    tenant, user = make_tenant_with_user()
    from django.utils import timezone

    release = AppRelease.objects.create(
        version="1.2.0", channel=AppRelease.Channel.STABLE,
        package_size=4, sha256="0" * 64,
        min_schema_version=1, max_schema_version=2,
        publication_status=AppRelease.Publication.PUBLISHED,
        published_at=timezone.now(),
    )
    device, token = enroll_device(APIClient(), user, tenant)
    response = APIClient().post(
        "/api/v1/updates/attempts/",
        {"release_id": release.pk, "state": "INSTALLED", "detail": "ok"},
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Device {token}",
    )
    assert response.status_code == 201, response.content
