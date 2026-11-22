"""Device-token authentication.

Header form: ``Authorization: Device <token>``. Token bodies are random; only
their SHA-256 hashes are stored. The authenticated device is the *only*
source of tenant context — client-supplied tenant identifiers are validated
against it, never trusted.
"""

from __future__ import annotations

from rest_framework import authentication, exceptions
from rest_framework.permissions import BasePermission
from rest_framework.throttling import AnonRateThrottle

from apps.devices.models import Device, DeviceToken


def _now():
    from django.utils import timezone

    return timezone.now()


class DeviceTokenAuthentication(authentication.BaseAuthentication):
    def authenticate(self, request):
        header = authentication.get_authorization_header(request).decode("utf-8")
        if not header.startswith("Device "):
            return None
        token = header[len("Device "):].strip()
        if not token:
            raise exceptions.AuthenticationFailed("missing device token")
        return self.authenticate_token(token)

    def authenticate_token(self, token: str):
        try:
            token_obj = DeviceToken.objects.select_related(
                "device", "device__tenant"
            ).get(token_hash=DeviceToken.hash_token(token))
        except DeviceToken.DoesNotExist:
            raise exceptions.AuthenticationFailed("unknown device token")
        if token_obj.revoked:
            raise exceptions.AuthenticationFailed("device token revoked")
        if token_obj.expires_at <= _now():
            raise exceptions.AuthenticationFailed("device token expired")
        device: Device = token_obj.device
        if device.status != Device.Status.ACTIVE:
            raise exceptions.AuthenticationFailed("device not authorized")
        device.last_seen_at = _now()
        device.save(update_fields=["last_seen_at"])
        return (token_obj, token_obj)

    def authenticate_header(self, request):
        return "Device"


class DeviceRateThrottle(AnonRateThrottle):
    """Rate limit for device-principal requests: the standard user throttle
    assumes a Django user; devices are throttled per token hash instead."""

    scope = "device"

    def get_cache_key(self, request, view):
        token_obj = getattr(request, "auth", None)
        if getattr(token_obj, "device_id", None) is None:
            return None
        ident = token_obj.token_hash[:16]
        return self.cache_format % {
            "scope": self.scope,
            "ident": ident,
        }


class IsDeviceOrUser(BasePermission):
    """Allow requests authenticated either as a registered device or as a user
    account. The standard IsAuthenticated permission cannot handle device
    principals (they are not Django users)."""

    def has_permission(self, request, view) -> bool:
        auth = getattr(request, "auth", None)
        if getattr(auth, "device_id", None) is not None:
            return True
        return bool(
            getattr(request, "user", None) is not None
            and getattr(request.user, "is_authenticated", False)
        )
