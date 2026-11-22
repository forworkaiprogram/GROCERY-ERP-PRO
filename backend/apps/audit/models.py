from django.conf import settings
from django.db import models

from apps.tenants.models import BaseModel


class AuditLog(BaseModel):
    """Append-only audit trail; rows are never updated or deleted by the app."""

    tenant = models.ForeignKey(
        "tenants.Tenant", null=True, blank=True, on_delete=models.PROTECT,
        related_name="audit_logs",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.PROTECT, related_name="audit_logs",
    )
    device = models.ForeignKey(
        "devices.Device", null=True, blank=True, on_delete=models.PROTECT,
        related_name="audit_logs",
    )
    action = models.CharField(max_length=120)
    target_type = models.CharField(max_length=64, blank=True)
    target_uuid = models.CharField(max_length=64, blank=True)
    detail = models.JSONField(default=dict, blank=True)
    at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-at"]
