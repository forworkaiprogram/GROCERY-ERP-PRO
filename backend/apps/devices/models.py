import hashlib
import secrets
import uuid as uuidlib

from django.conf import settings
from django.db import models

from apps.tenants.models import BaseModel, Branch, Tenant


class Device(BaseModel):
    class Status(models.TextChoices):
        PENDING = "PENDING"
        ACTIVE = "ACTIVE"
        REVOKED = "REVOKED"

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="devices")
    device_uuid = models.UUIDField(default=uuidlib.uuid4, unique=True)
    name = models.CharField(max_length=120)
    branch = models.ForeignKey(Branch, null=True, on_delete=models.SET_NULL)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    registered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL
    )
    last_seen_at = models.DateTimeField(null=True, blank=True)
    app_version = models.CharField(max_length=32, blank=True)


class DeviceToken(BaseModel):
    """Bearer token for device sync; only its hash is stored."""

    device = models.ForeignKey(Device, on_delete=models.CASCADE, related_name="tokens")
    token_hash = models.CharField(max_length=64, unique=True)
    expires_at = models.DateTimeField()
    revoked = models.BooleanField(default=False)

    @staticmethod
    def hash_token(token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()

    @staticmethod
    def issue(device: Device, days: int = 365) -> str:
        token = secrets.token_urlsafe(32)
        from django.utils import timezone
        from datetime import timedelta

        DeviceToken.objects.create(
            device=device,
            token_hash=DeviceToken.hash_token(token),
            expires_at=timezone.now() + timedelta(days=days),
        )
        return token
