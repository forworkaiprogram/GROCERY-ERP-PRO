"""User-facing authentication endpoints (the EXE's cloud login)."""

from __future__ import annotations

from django.contrib.auth import authenticate
from rest_framework import exceptions, serializers
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.authentication import UserToken
from apps.accounts.models import Membership


class LoginSerializer(serializers.Serializer):
    username = serializers.CharField()
    password = serializers.CharField(write_only=True)


class LoginView(APIView):
    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = authenticate(
            request,
            username=serializer.validated_data["username"],
            password=serializer.validated_data["password"],
        )
        if user is None:
            raise exceptions.AuthenticationFailed("invalid credentials")
        token = UserToken.issue(user)
        memberships = [
            {"tenant_id": str(m.tenant.uuid), "tenant_name": m.tenant.name,
             "role": m.role}
            for m in Membership.objects.filter(
                user=user, is_active=True
            ).select_related("tenant")
        ]
        return Response({"token": token, "memberships": memberships})


class MeView(APIView):
    def get(self, request):
        user = request.user
        memberships = [
            {"tenant_id": str(m.tenant.uuid), "tenant_name": m.tenant.name,
             "role": m.role, "is_super_admin": m.role == Membership.Role.SUPER_ADMIN}
            for m in Membership.objects.filter(
                user=user, is_active=True
            ).select_related("tenant")
        ]
        return Response(
            {"username": user.username,
             "is_platform_admin": memberships and any(
                 m["is_super_admin"] for m in memberships)}
        )
