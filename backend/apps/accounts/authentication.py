"""User authentication for the desktop EXE.

Session-free token authentication: the EXE logs a tenant member in with
username+password and receives an opaque bearer token stored (hashed) in the
local auth cache. Tokens are stored only as SHA-256 hashes server-side.
"""

from __future__ import annotations

import hashlib
import secrets

from django.conf import settings
from django.contrib.auth import authenticate
from django.db import models
from rest_framework import authentication, exceptions

from apps.tenants.models import BaseModel


class UserToken(BaseModel):
    """Opaque bearer token for a human user; only its hash is stored."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="api_tokens"
    )
    token_hash = models.CharField(max_length=64, unique=True)
    revoked = models.BooleanField(default=False)

    @staticmethod
    def hash_token(token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()

    @staticmethod
    def issue(user) -> str:
        token = secrets.token_urlsafe(32)
        UserToken.objects.create(user=user, token_hash=UserToken.hash_token(token))
        return token


class BearerAuthentication(authentication.BaseAuthentication):
    def authenticate(self, request):
        header = authentication.get_authorization_header(request).decode("utf-8")
        if not header.startswith("Bearer "):
            return None
        token = header[len("Bearer "):].strip()
        if not token:
            raise exceptions.AuthenticationFailed("missing bearer token")
        try:
            token_obj = UserToken.objects.select_related("user").get(
                token_hash=UserToken.hash_token(token)
            )
        except UserToken.DoesNotExist:
            raise exceptions.AuthenticationFailed("invalid bearer token")
        if token_obj.revoked or not token_obj.user.is_active:
            raise exceptions.AuthenticationFailed("token revoked or user inactive")
        return (token_obj.user, token_obj)

    def authenticate_header(self, request):
        return "Bearer"
