"""SaaS plans, subscriptions, and manual (gateway-agnostic) payments.

Subscription lifecycle only gates functionality; it NEVER deletes tenant
business data. Expiration lowers enforcement to the signed entitlement
snapshot's grace logic on the desktop (see
desktop/services/entitlements.py) and, beyond grace, to the offline lite
set. Plan restrictions are configuration, not scattered hardcoding.
"""

from __future__ import annotations

from django.db import models
from django.utils import timezone

from apps.tenants.models import BaseModel, Tenant


class Plan(BaseModel):
    class BillingCycle(models.TextChoices):
        MONTHLY = "MONTHLY"
        ANNUAL = "ANNUAL"

    code = models.SlugField(unique=True)
    name = models.CharField(max_length=120)
    is_active = models.BooleanField(default=True)
    price_yer = models.DecimalField(max_digits=16, decimal_places=2)
    billing_cycle = models.CharField(
        max_length=12, choices=BillingCycle.choices, default=BillingCycle.MONTHLY
    )
    trial_days = models.PositiveIntegerField(default=0)
    # Extensible entitlement limits (branch/user/device/warehouse counts,
    # feature flags). Updated by Super Admin; read by the snapshot builder.
    entitlements = models.JSONField(default=dict, blank=True)


class Subscription(BaseModel):
    class Status(models.TextChoices):
        TRIAL = "TRIAL"
        ACTIVE = "ACTIVE"
        GRACE = "GRACE"
        EXPIRED = "EXPIRED"
        SUSPENDED = "SUSPENDED"
        CANCELLED = "CANCELLED"

    tenant = models.ForeignKey(
        Tenant, on_delete=models.PROTECT, related_name="subscriptions"
    )
    plan = models.ForeignKey(Plan, on_delete=models.PROTECT, related_name="subscriptions")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.TRIAL)
    started_at = models.DateTimeField(default=timezone.now)
    current_period_end = models.DateTimeField()
    cancelled_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]

    def effective_status(self, now=None) -> str:
        now = now or timezone.now()
        if self.status == self.Status.ACTIVE and now > self.current_period_end:
            return self.Status.GRACE
        return self.status


class SubscriptionPayment(BaseModel):
    """A declared payment awaiting manual verification by a platform admin.

    Deliberately gateway-agnostic: no payment provider is assumed anywhere in
    the codebase (per the product's Yemen-market constraint).
    """

    class Method(models.TextChoices):
        CASH = "CASH"
        BANK_TRANSFER = "BANK_TRANSFER"
        MANUAL_OTHER = "MANUAL_OTHER"

    class Status(models.TextChoices):
        PENDING = "PENDING"
        VERIFIED = "VERIFIED"
        REJECTED = "REJECTED"

    subscription = models.ForeignKey(
        Subscription, on_delete=models.PROTECT, related_name="payments"
    )
    amount_yer = models.DecimalField(max_digits=16, decimal_places=2)
    method = models.CharField(max_length=16, choices=Method.choices)
    reference = models.CharField(max_length=120, blank=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING)
    declared_at = models.DateTimeField(auto_now_add=True)
    verified_by = models.ForeignKey(
        "accounts.User", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="verified_subscription_payments",
    )
    verified_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)
