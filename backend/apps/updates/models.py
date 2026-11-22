"""Application releases and device update bookkeeping.

Only platform administrators (SUPER_ADMIN membership role) publish releases.
The signing private key never leaves the server; the signed manifest, not
the release row, is what devices verify.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models

from apps.accounts.models import Membership
from apps.tenants.models import BaseModel


class AppRelease(BaseModel):
    class Channel(models.TextChoices):
        STABLE = "stable"
        BETA = "beta"
        INTERNAL = "internal"

    class Publication(models.TextChoices):
        DRAFT = "DRAFT"
        PUBLISHED = "PUBLISHED"
        PAUSED = "PAUSED"
        WITHDRAWN = "WITHDRAWN"

    app_id = models.CharField(max_length=64, default="grocery-erp-pro")
    version = models.CharField(max_length=32)
    build = models.PositiveIntegerField(default=1)
    channel = models.CharField(max_length=12, choices=Channel.choices)
    release_notes = models.TextField(blank=True)
    required = models.BooleanField(default=False)
    package = models.FileField(upload_to="releases/")
    package_size = models.BigIntegerField()
    sha256 = models.CharField(max_length=64)
    min_schema_version = models.PositiveIntegerField()
    max_schema_version = models.PositiveIntegerField()
    min_supported_version = models.CharField(max_length=32, blank=True)
    supported_windows = models.CharField(max_length=120, default="10,11")
    rollout_percentage = models.PositiveSmallIntegerField(default=100)
    published_at = models.DateTimeField(null=True, blank=True)
    publication_status = models.CharField(
        max_length=12, choices=Publication.choices, default=Publication.DRAFT
    )
    published_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("app_id", "version", "channel"),
                name="uniq_release_version_channel",
            )
        ]
        ordering = ["-version", "-build"]

    def is_for_role_publisher(self, user) -> bool:
        return Membership.objects.filter(
            user=user, role=Membership.Role.SUPER_ADMIN, is_active=True
        ).exists()


class UpdateAttempt(BaseModel):
    """Device-reported update outcome; used for rollout monitoring."""

    release = models.ForeignKey(
        AppRelease, on_delete=models.CASCADE, related_name="attempts"
    )
    device = models.ForeignKey(
        "devices.Device", on_delete=models.CASCADE, related_name="update_attempts"
    )
    state = models.CharField(max_length=24)  # DOWNLOADED/INSTALLED/FAILED...
    detail = models.TextField(blank=True)
