from django.urls import path

from apps.subscriptions import views

urlpatterns = [
    path("snapshot/", views.SnapshotView.as_view()),
    path("status/", views.SubscriptionStatusView.as_view()),
    path("payments/declare/", views.DeclarePaymentView.as_view()),
]
