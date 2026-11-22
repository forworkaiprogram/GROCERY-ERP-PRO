from django.urls import path

from apps.synchronization import views

urlpatterns = [
    path("events/", views.SyncIngestView.as_view()),
]
