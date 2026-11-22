from django.contrib import admin
from django.http import JsonResponse
from django.urls import include, path


def health(request):
    return JsonResponse({"status": "ok"})


api_v1 = [
    path("health/", health),
    path("", include("apps.accounts.urls")),
    path("devices/", include("apps.devices.urls")),
    path("sync/", include("apps.synchronization.urls")),
    path("subscriptions/", include("apps.subscriptions.urls")),
    path("updates/", include("apps.updates.urls")),
    path("admin/", admin.site.urls),
]

urlpatterns = [
    path("api/v1/", include(api_v1)),
]
