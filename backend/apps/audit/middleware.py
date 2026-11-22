"""Request-scoped audit logging middleware.

Records an append-only AuditLog row for every state-changing API request
(POST/PUT/PATCH/DELETE) that reaches the application, enriching it with the
authenticated principal: a tenant user, a device, or both.
"""

from __future__ import annotations

import logging

logger = logging.getLogger("audit")

AUDITED_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


class AuditMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        try:
            self.log_request(request, response)
        except Exception:
            logger.exception("audit logging failed for %s", request.path)
        return response

    def log_request(self, request, response) -> None:
        if request.method not in AUDITED_METHODS:
            return
        if not 200 <= response.status_code < 300:
            return
        user = getattr(request, "user", None)
        device = None
        token = getattr(request, "auth", None)
        if hasattr(token, "device_id"):
            device = token.device
        from apps.audit.models import AuditLog

        tenant = None
        if hasattr(token, "device") and getattr(token, "device", None) is not None:
            tenant = token.device.tenant
        elif getattr(user, "is_authenticated", False):
            tenant_id = getattr(request, "tenant_id", None)
            if tenant_id is not None:
                tenant = self._tenant(tenant_id)

        AuditLog.objects.create(
            tenant=tenant,
            user=user if getattr(user, "is_authenticated", False) else None,
            device=device,
            action=f"{request.method} {request.path}",
            detail={"status_code": response.status_code},
        )

    @staticmethod
    def _tenant(tenant_id):
        from apps.tenants.models import Tenant

        try:
            return Tenant.objects.get(pk=tenant_id)
        except (Tenant.DoesNotExist, ValueError, TypeError):
            return None
