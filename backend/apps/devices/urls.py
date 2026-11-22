from django.urls import path

from apps.devices import views

urlpatterns = [
    path("enroll/", views.DeviceEnrollView.as_view()),
    path("refresh-token/", views.DeviceRefreshTokenView.as_view()),
    path("whoami/", views.DeviceWhoAmIView.as_view()),
    path("", views.TenantScopedDeviceView.as_view()),
]
