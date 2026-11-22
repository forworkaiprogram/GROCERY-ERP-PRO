from django.urls import path

from apps.accounts import views

urlpatterns = [
    path("auth/login/", views.LoginView.as_view()),
    path("auth/me/", views.MeView.as_view()),
]
