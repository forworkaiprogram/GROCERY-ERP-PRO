import uuid as uuidlib

from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models

from apps.tenants.models import BaseModel, Branch, Tenant


class Membership(BaseModel):
    class Role(models.TextChoices):
        OWNER = "OWNER"
        MANAGER = "MANAGER"
        ACCOUNTANT = "ACCOUNTANT"
        CASHIER = "CASHIER"
        INVENTORY = "INVENTORY_MANAGER"
        PURCHASING = "PURCHASING"
        HR = "HR_OFFICER"
        SUPER_ADMIN = "SUPER_ADMIN"

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="memberships")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="memberships"
    )
    role = models.CharField(max_length=24, choices=Role.choices)
    branch = models.ForeignKey(
        Branch, null=True, blank=True, on_delete=models.SET_NULL
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("tenant", "user"), condition=models.Q(is_active=True),
                name="uniq_active_membership",
            )
        ]


class User(AbstractUser):
    uuid = models.UUIDField(default=uuidlib.uuid4, editable=False, unique=True)
    mfa_enabled = models.BooleanField(default=False)
    mfa_secret = models.CharField(max_length=64, blank=True)  # encrypted at rest in prod
    phone = models.CharField(max_length=32, blank=True)

    def memberships_for(self, tenant_id) -> models.QuerySet:
        return self.memberships.filter(tenant_id=tenant_id, is_active=True)
