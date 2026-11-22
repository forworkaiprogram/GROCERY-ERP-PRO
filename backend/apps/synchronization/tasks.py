"""Sync health reporting for the platform dashboard.

Flags tenants whose devices stopped acknowledging events; read by Super
Admin tooling. Read-only: it never mutates business events.
"""

from celery import shared_task
from django.utils import timezone


@shared_task()
def sync_health_report(max_staleness_minutes: int = 60) -> dict:
    from datetime import timedelta

    from apps.devices.models import Device
    from apps.tenants.models import Tenant

    threshold = timezone.now() - timedelta(minutes=max_staleness_minutes)
    stale = Device.objects.filter(
        status=Device.Status.ACTIVE, last_seen_at__lt=threshold
    )
    return {
        "checked_at": timezone.now().isoformat(),
        "active_tenants": Tenant.objects.filter(status="ACTIVE").count(),
        "stale_active_devices": stale.count(),
    }
