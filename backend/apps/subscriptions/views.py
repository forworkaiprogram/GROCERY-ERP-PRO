"""Subscription and entitlement endpoints.

- Devices fetch their tenant's signed entitlement snapshot for offline
  enforcement. The tenant ALWAYS comes from the authenticated principal.
- Tenant members can see their own subscription status and declare payments
  (manual verification workflow, status PENDING until platform review).
"""

from __future__ import annotations

import logging

from django.conf import settings
from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.authentication import BearerAuthentication
from apps.accounts.models import Membership
from apps.audit.models import AuditLog
from apps.devices.auth import (
    DeviceRateThrottle,
    DeviceTokenAuthentication,
    IsDeviceOrUser,
)
from apps.subscriptions.models import Subscription, SubscriptionPayment
from apps.subscriptions.signing import (
    SigningKeyUnavailable,
    load_signing_key,
    sign_payload,
)

logger = logging.getLogger("subscriptions")

ENTITLEMENT_KEYS = (
    "max_branches", "max_users", "max_devices", "max_warehouses",
    "advanced_reports", "payroll", "accounting", "cloud_sync", "storage_mb",
    "integrations", "hr",
)


class SnapshotView(APIView):
    """Signed entitlement snapshot for offline enforcement on the desktop."""

    authentication_classes = [DeviceTokenAuthentication, BearerAuthentication]
    throttle_classes = [DeviceRateThrottle]
    permission_classes = [IsDeviceOrUser]

    def get(self, request):
        token_obj = request.auth
        device = getattr(token_obj, "device", None)
        if device is not None:
            tenant = device.tenant
        else:
            return Response(
                {"detail": "entitlement snapshots are issued to registered devices"},
                status=status.HTTP_403_FORBIDDEN,
            )
        subscription = Subscription.objects.select_related("plan").filter(
            tenant=tenant
        ).order_by("-created_at").first()
        now = timezone.now()
        if subscription is None:
            return Response(
                {"detail": "tenant has no subscription"}, status=404
            )
        effective = subscription.effective_status(now)
        from datetime import timedelta as _timedelta

        grace_deadline = (
            subscription.current_period_end
            + _timedelta(hours=settings.ENTITLEMENT_GRACE_HOURS)
        )
        beyond_grace = effective in (
            Subscription.Status.EXPIRED,
            Subscription.Status.CANCELLED,
        ) or now > grace_deadline
        if beyond_grace:
            # Beyond the configured offline grace: the snapshot still verifies
            # and reports facts, but no plan entitlements are served. The
            # desktop lowers itself to the offline lite set; business data is
            # untouched in every path.
            entitlements = {}
        elif effective == Subscription.Status.GRACE:
            entitlements = {}
        else:
            entitlements = dict(subscription.plan.entitlements or {})
        payload = {
            "tenant_id": str(tenant.uuid),
            "plan": subscription.plan.code,
            "entitlements": entitlements,
            "subscription_status": effective,
            "signed_at": now.isoformat(),
            "valid_until": subscription.current_period_end.isoformat(),
        }
        try:
            signing_key = load_signing_key(settings.ENTITLEMENT_SIGNING_KEY_PATH)
        except SigningKeyUnavailable as exc:
            logger.error("entitlement snapshot not signed: %s", exc)
            return Response(
                {"detail": "signing key unavailable; snapshot withheld"},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        signed = sign_payload(payload, signing_key)
        AuditLog.objects.create(
            tenant=tenant, device=device, action="subscription.snapshot_issued",
            target_type="subscription", target_uuid=str(subscription.uuid),
        )
        return Response(signed)


class SubscriptionStatusView(APIView):
    def get(self, request):
        tenant_uuid = request.query_params.get("tenant_uuid")
        try:
            membership = Membership.objects.select_related("tenant").get(
                user=request.user, tenant__uuid=tenant_uuid, is_active=True
            )
        except Membership.DoesNotExist:
            return Response({"detail": "not found"},
                            status=status.HTTP_404_NOT_FOUND)
        subscription = Subscription.objects.select_related("plan").filter(
            tenant=membership.tenant
        ).order_by("-created_at").first()
        if subscription is None:
            return Response({"status": "NONE"})
        return Response({
            "plan": subscription.plan.code,
            "plan_name": subscription.plan.name,
            "status": subscription.effective_status(),
            "current_period_end": subscription.current_period_end,
            "price_yer": subscription.plan.price_yer,
        })


class DeclarePaymentView(APIView):
    """A tenant member declares a payment; it stays PENDING until a platform
    administrator verifies it (manual, gateway-agnostic workflow)."""

    def post(self, request):
        input_serializer = DeclarePaymentSerializer(data=request.data)
        input_serializer.is_valid(raise_exception=True)
        data = input_serializer.validated_data
        try:
            membership = Membership.objects.select_related("tenant").get(
                user=request.user, tenant__uuid=data["tenant_uuid"], is_active=True
            )
        except Membership.DoesNotExist:
            return Response({"detail": "not found"},
                            status=status.HTTP_404_NOT_FOUND)
        subscription = Subscription.objects.select_related("plan").filter(
            tenant=membership.tenant
        ).order_by("-created_at").first()
        if subscription is None:
            return Response({"detail": "tenant has no subscription"}, status=404)
        payment = SubscriptionPayment.objects.create(
            subscription=subscription,
            amount_yer=data["amount_yer"],
            method=data["method"],
            reference=data.get("reference", ""),
        )
        AuditLog.objects.create(
            tenant=membership.tenant, user=request.user,
            action="subscription.payment_declared",
            target_type="subscription_payment", target_uuid=str(payment.uuid),
            detail={"amount_yer": str(data["amount_yer"]), "method": data["method"]},
        )
        return Response({"payment_id": str(payment.uuid), "status": payment.status},
                        status=status.HTTP_201_CREATED)


class DeclarePaymentSerializer(serializers.Serializer):
    tenant_uuid = serializers.UUIDField()
    amount_yer = serializers.DecimalField(max_digits=16, decimal_places=2)
    method = serializers.ChoiceField(choices=SubscriptionPayment.Method.choices)
    reference = serializers.CharField(
        max_length=120, required=False, allow_blank=True, default=""
    )
