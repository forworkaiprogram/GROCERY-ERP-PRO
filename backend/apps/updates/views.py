"""Release distribution and authorized release management.

GET /api/v1/updates/releases/?channel=stable returns the signed manifest list
consumed by the desktop Update Center; each manifest carries every field the
desktop verifier requires and is signed with the platform Ed25519 key. The
private key never leaves the server.

Release publication and lifecycle control (publish/pause/withdraw) are ONLY
for platform administrators; a tenant admin can never mint releases.
"""

from __future__ import annotations

import hashlib
import logging

from django.conf import settings
from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import Membership
from apps.devices.auth import (
    DeviceRateThrottle,
    DeviceTokenAuthentication,
    IsDeviceOrUser,
)
from apps.updates.manifests import (
    SigningKeyUnavailable,
    load_signing_key,
    sign_manifest,
)
from apps.updates.models import AppRelease, UpdateAttempt

logger = logging.getLogger("updates")

MANIFEST_REQUIRED_FIELDS = (
    "app_id", "version", "build", "channel", "package_url", "package_size",
    "sha256", "min_schema_version", "max_schema_version", "required",
    "published_at",
)


def is_platform_admin(user) -> bool:
    if not getattr(user, "is_authenticated", False):
        return False
    return Membership.objects.filter(
        user=user, role=Membership.Role.SUPER_ADMIN, is_active=True
    ).exists()


def manifest_payload(release: AppRelease, request) -> dict:
    url = request.build_absolute_uri(release.package.url) if release.package else ""
    return {
        "app_id": release.app_id,
        "version": release.version,
        "build": release.build,
        "channel": release.channel,
        "package_url": url,
        "package_size": release.package_size,
        "sha256": release.sha256,
        "min_schema_version": release.min_schema_version,
        "max_schema_version": release.max_schema_version,
        "required": release.required,
        "release_notes": release.release_notes,
        "published_at": release.published_at.isoformat() if release.published_at else "",
    }


class ReleaseListView(APIView):
    """Signed manifest list for the desktop Update Center (no secrets)."""

    def get(self, request):
        channel = request.query_params.get("channel", "stable")
        if channel not in AppRelease.Channel.values:
            return Response({"releases": [], "detail": "unknown channel"})
        releases = AppRelease.objects.filter(
            channel=channel, publication_status=AppRelease.Publication.PUBLISHED
        ).order_by("-version", "-build")[:20]
        try:
            signing_key = load_signing_key(settings.UPDATE_SIGNING_KEY_PATH)
        except SigningKeyUnavailable as exc:
            logger.error("release list unsigned: %s", exc)
            return Response(
                {"detail": "signing key unavailable; releases withheld"},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        # Gradual-rollout staging in this implementation is channel-based
        # (internal -> beta -> stable) and manual (pause/withdraw). The
        # percentage field is recorded and exposed to Super Admin tooling;
        # per-device percentage gating is not applied here because the
        # update-check request is unauthenticated by contract (the desktop
        # Update Center sends no device credentials) — gating it would claim
        # protection that does not exist. Documented in
        # documentation/updates/UPDATES.md.
        signed = [
            sign_manifest(manifest_payload(release, request), signing_key)
            for release in releases
        ]
        return Response({"releases": signed})


class ReleasePublishView(APIView):
    """Upload + publish a release. Platform administrators only."""

    def post(self, request):
        if not is_platform_admin(request.user):
            return Response(
                {"detail": "only platform administrators may publish releases"},
                status=status.HTTP_403_FORBIDDEN,
            )
        input_serializer = ReleaseInputSerializer(data=request.data)
        input_serializer.is_valid(raise_exception=True)
        data = input_serializer.validated_data
        package = request.FILES.get("package")
        if package is None:
            return Response({"package": ["uploaded package file is required"]},
                            status=status.HTTP_400_BAD_REQUEST)
        digest = hashlib.sha256()
        size = 0
        for chunk in package.chunks():
            digest.update(chunk)
            size += len(chunk)
        release = AppRelease.objects.create(
            version=data["version"],
            build=data.get("build", 1),
            channel=data["channel"],
            release_notes=data.get("release_notes", ""),
            required=bool(data.get("required", False)),
            package=package,
            package_size=size,
            sha256=digest.hexdigest(),
            min_schema_version=data["min_schema_version"],
            max_schema_version=data["max_schema_version"],
            published_by=request.user,
            publication_status=AppRelease.Publication.PUBLISHED,
            published_at=timezone.now(),
        )
        return Response({"release_id": release.pk, "sha256": release.sha256,
                         "package_size": release.package_size},
                        status=status.HTTP_201_CREATED)


class ReleaseManageView(APIView):
    """Pause, resume, or withdraw a release. Platform administrators only."""

    def post(self, request):
        if not is_platform_admin(request.user):
            return Response(
                {"detail": "only platform administrators may manage releases"},
                status=status.HTTP_403_FORBIDDEN,
            )
        action = request.data.get("action")
        release_id = request.data.get("release_id")
        transitions = {
            "pause": AppRelease.Publication.PAUSED,
            "resume": AppRelease.Publication.PUBLISHED,
            "withdraw": AppRelease.Publication.WITHDRAWN,
        }
        if action not in transitions or not release_id:
            return Response({"detail": "action must be pause|resume|withdraw"
                                     " and release_id is required"},
                            status=status.HTTP_400_BAD_REQUEST)
        try:
            release = AppRelease.objects.get(pk=release_id)
        except AppRelease.DoesNotExist:
            return Response({"detail": "not found"},
                            status=status.HTTP_404_NOT_FOUND)
        release.publication_status = transitions[action]
        release.save(update_fields=["publication_status", "updated_at"])
        return Response({"release_id": release.pk,
                         "publication_status": release.publication_status})


class ReleaseInputSerializer(serializers.Serializer):
    version = serializers.CharField(max_length=32)
    build = serializers.IntegerField(min_value=1, required=False, default=1)
    channel = serializers.ChoiceField(choices=AppRelease.Channel.choices)
    release_notes = serializers.CharField(required=False, allow_blank=True,
                                          default="")
    required = serializers.BooleanField(required=False, default=False)
    min_schema_version = serializers.IntegerField(min_value=0)
    max_schema_version = serializers.IntegerField(min_value=0)

    def validate(self, attrs):
        if attrs["max_schema_version"] < attrs["min_schema_version"]:
            raise serializers.ValidationError(
                "max_schema_version must be >= min_schema_version"
            )
        return attrs


class UpdateAttemptView(APIView):
    """Devices report download/install outcomes for rollout monitoring."""

    authentication_classes = [DeviceTokenAuthentication]
    throttle_classes = [DeviceRateThrottle]
    permission_classes = [IsDeviceOrUser]

    def post(self, request):
        release_id = request.data.get("release_id")
        state = request.data.get("state")
        if not release_id or not state:
            return Response({"detail": "release_id and state are required"},
                            status=status.HTTP_400_BAD_REQUEST)
        try:
            release = AppRelease.objects.get(pk=release_id)
        except AppRelease.DoesNotExist:
            return Response({"detail": "not found"},
                            status=status.HTTP_404_NOT_FOUND)
        attempt = UpdateAttempt.objects.create(
            release=release, device=request.auth.device,
            state=str(state)[:24],
            detail=str(request.data.get("detail", ""))[:2000],
        )
        return Response({"attempt_id": attempt.pk}, status=status.HTTP_201_CREATED)
