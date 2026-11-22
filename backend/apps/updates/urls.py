from django.urls import path

from apps.updates import views

urlpatterns = [
    path("releases/", views.ReleaseListView.as_view()),
    path("releases/publish/", views.ReleasePublishView.as_view()),
    path("releases/manage/", views.ReleaseManageView.as_view()),
    path("attempts/", views.UpdateAttemptView.as_view()),
]
