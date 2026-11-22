"""Device enrollment, listing, revocation, and token refresh.

A tenant member authenticates as a user (BearerAuthentication) to register a
device; the device then authenticates on its own with the issued opaque
token. Every endpoint resolves the tenant through the caller's active
membership or the authenticated device — never from client-supplied IDs
standing alone.
"""

from __future__ import annotations

import logging

from django.db import transaction as db_tx
from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import Membership
from apps.audit.models import AuditLog
from apps.devices.auth import (
    DeviceRateThrottle,
    DeviceTokenAuthentication,
    IsDeviceOrUser,
)
from apps.devices.models import Device, DeviceToken
from apps.tenants.models import Branch

logger = logging.getLogger("devices")


def active_tenant_for(user, tenant_uuid):
    try:
        membership = Membership.objects.select_related("tenant").get(
            user=user, tenant__uuid=tenant_uuid, is_active=True
        )
    except Membership.DoesNotExist:
        raise serializers.ValidationError(
            {"tenant_uuid": "no active membership in this tenant"}
        )
    return membership.tenant


class DeviceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Device
        fields = ("uuid", "device_uuid", "name", "status", "last_seen_at")
        read_only_fields = fields


class DeviceEnrollView(APIView):
    """Register a device in the caller's tenant and return its token once."""

    def post(self, request):
        tenant_uuid = request.data.get("tenant_uuid")
        if not tenant_uuid:
            return Response(
                {"tenant_uuid": ["this field is required"]},
                status=status.HTTP_400_BAD_REQUEST,
            )
        tenant = active_tenant_for(request.user, tenant_uuid)
        name = request.data.get("name") or "Unnamed device"
        branch = None
        branch_uuid = request.data.get("branch_uuid")
        if branch_uuid:
            try:
                branch = Branch.objects.get(uuid=branch_uuid, tenant=tenant)
            except Branch.DoesNotExist:
                return Response(
                    {"branch_uuid": ["branch not found in this tenant"]},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        with db_tx.atomic():
            device = Device.objects.create(
                tenant=tenant,
                name=name,
                branch=branch,
                status=Device.Status.ACTIVE,
                registered_by=request.user,
            )
            token = DeviceToken.issue(device)
            AuditLog.objects.create(
                tenant=tenant, user=request.user, device=device,
                action="device.enroll", target_type="device",
                target_uuid=str(device.uuid),
            )
        return Response(
            {"device_uuid": str(device.device_uuid), "token": token,
             "tenant_id": str(tenant.uuid)},
            status=status.HTTP_201_CREATED,
        )


class DeviceRefreshTokenView(APIView):
    """Revoke the presented token and issue a fresh one for the same device."""

    authentication_classes = [DeviceTokenAuthentication]
    throttle_classes = [DeviceRateThrottle]
    permission_classes = [IsDeviceOrUser]

    def post(self, request):
        token_obj = request.auth
        with db_tx.atomic():
            token_obj.revoked = True
            token_obj.save(update_fields=["revoked"])
            new_token = DeviceToken.issue(token_obj.device)
            AuditLog.objects.create(
                tenant=token_obj.device.tenant, device=token_obj.device,
                action="device.token_refresh", target_type="device_token",
                target_uuid=str(token_obj.uuid),
            )
        return Response({"token": new_token}, status=status.HTTP_200_OK)


class TenantScopedDeviceView(APIView):
    throttle_classes = [DeviceRateThrottle]
    """List or revoke devices of a tenant the caller actively belongs to."""

    def get(self, request):
        tenant_uuid = request.query_params.get("tenant_uuid")
        if not tenant_uuid:
            return Response(
                {"tenant_uuid": ["this query parameter is required"]},
                status=status.HTTP_400_BAD_REQUEST,
            )
        tenant = active_tenant_for(request.user, tenant_uuid)
        devices = Device.objects.filter(tenant=tenant).select_related("branch")
        return Response(DeviceSerializer(devices, many=True).data)

    def post(self, request):
        tenant_uuid = request.data.get("tenant_uuid")
        device_uuid = request.data.get("device_uuid")
        if not tenant_uuid or not device_uuid:
            return Response(
                {"detail": "tenant_uuid and device_uuid are required"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        tenant = active_tenant_for(request.user, tenant_uuid)
        try:
            device = Device.objects.get(device_uuid=device_uuid, tenant=tenant)
        except Device.DoesNotExist:
            return Response({"detail": "not found"},
                            status=status.HTTP_404_NOT_FOUND)
        with db_tx.atomic():
            device.status = Device.Status.REVOKED
            device.save(update_fields=["status"])
            DeviceToken.objects.filter(device=device).update(revoked=True)
            AuditLog.objects.create(
                tenant=tenant, user=request.user, device=device,
                action="device.revoke", target_type="device",
                target_uuid=str(device.uuid),
            )
        return Response({"detail": "revoked"}, status=status.HTTP_200_OK)


class DeviceWhoAmIView(APIView):
    """Let a device confirm its own identity and tenant binding."""

    authentication_classes = [DeviceTokenAuthentication]
    throttle_classes = [DeviceRateThrottle]
    permission_classes = [IsDeviceOrUser]

    def get(self, request):
        device = request.auth.device
        return Response(DeviceSerializer(device).data)
