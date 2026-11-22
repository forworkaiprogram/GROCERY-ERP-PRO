"""Background subscription housekeeping.

Period sweep moves ACTIVE subscriptions whose period ended into GRACE, and
GRACE subscriptions past the configured offline grace into EXPIRED. It only
updates subscription status; no tenant business data is ever touched.
"""

from celery import shared_task
from django.conf import settings
from django.utils import timezone


@shared_task()
def sweep_subscription_periods() -> dict:
    from apps.subscriptions.models import Subscription

    from datetime import timedelta

    now = timezone.now()
    moved_to_grace = Subscription.objects.filter(
        status=Subscription.Status.ACTIVE,
        current_period_end__lt=now,
    ).update(status=Subscription.Status.GRACE)
    grace_hours = getattr(settings, "ENTITLEMENT_GRACE_HOURS", 72)
    expired = Subscription.objects.filter(
        status=Subscription.Status.GRACE,
        current_period_end__lt=now - timedelta(hours=grace_hours),
    ).update(status=Subscription.Status.EXPIRED)
    return {"moved_to_grace": moved_to_grace, "expired": expired}
