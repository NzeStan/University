from __future__ import annotations

import re
from typing import Any

from django.http import HttpResponse, StreamingHttpResponse
from rest_framework import permissions, serializers, status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from university.core.api.pagination import PageNumberPagination
from university.core.api.schema import OpenApiTypes, extend_schema, paginated
from university.core.api.serializers import StrictModelSerializer
from university.core.exceptions import NotFound
from university.media import services
from university.media.library import Library
from university.media.models import AssetKind, MediaAsset

RANGE_RE = re.compile(r"^bytes=(\d*)-(\d*)$")
CHUNK = 256 * 1024


class MediaAssetSerializer(StrictModelSerializer):
    variants = serializers.SerializerMethodField()
    url = serializers.SerializerMethodField()

    class Meta:
        model = MediaAsset
        fields = (
            "id",
            "kind",
            "status",
            "mime_type",
            "size",
            "original_name",
            "duration_seconds",
            "width",
            "height",
            "error",
            "variants",
            "url",
            "created_at",
            "processed_at",
        )
        read_only_fields = fields

    def get_variants(self, obj: MediaAsset) -> list[str]:
        return list(obj.variants.values_list("name", flat=True))

    def get_url(self, obj: MediaAsset) -> str | None:
        """The owner's own short-lived link (ready assets only)."""
        return Library().url(obj.pk) if obj.status == "ready" else None


class MediaFileUploadSerializer(serializers.Serializer):
    file = serializers.FileField()
    kind = serializers.ChoiceField(choices=AssetKind.choices, required=False)


class MediaDirectStartSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=AssetKind.choices)
    mime_type = serializers.CharField(max_length=100)
    size = serializers.IntegerField(min_value=1)
    filename = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")


class MediaDirectSlotSerializer(serializers.Serializer):
    upload_id = serializers.UUIDField()
    url = serializers.CharField()
    method = serializers.CharField()
    headers = serializers.DictField(child=serializers.CharField())
    expires_at = serializers.DateTimeField()


class MediaClipSerializer(serializers.Serializer):
    start_seconds = serializers.FloatField(min_value=0)
    end_seconds = serializers.FloatField(min_value=0)


class MediaListCreateView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    @extend_schema(responses=paginated(MediaAssetSerializer))
    def get(self, request: Request) -> Response:
        paginator = PageNumberPagination()
        qs = MediaAsset.objects.filter(owner=request.user).order_by("-created_at")
        page = paginator.paginate_queryset(qs, request, view=self)
        return paginator.get_paginated_response(MediaAssetSerializer(page, many=True).data)

    @extend_schema(request=MediaFileUploadSerializer, responses={201: MediaAssetSerializer})
    def post(self, request: Request) -> Response:
        serializer = MediaFileUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        asset = services.upload(owner=request.user, **serializer.validated_data)
        return Response(MediaAssetSerializer(asset).data, status=status.HTTP_201_CREATED)


class MediaDetailView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def _own(self, request: Request, asset_id: Any) -> MediaAsset:
        asset = MediaAsset.objects.filter(pk=asset_id, owner=request.user).first()
        if asset is None:
            raise NotFound("Media not found.")
        return asset

    @extend_schema(responses=MediaAssetSerializer)
    def get(self, request: Request, asset_id: Any) -> Response:
        return Response(MediaAssetSerializer(self._own(request, asset_id)).data)

    @extend_schema(responses={204: None})
    def delete(self, request: Request, asset_id: Any) -> Response:
        services.delete_asset(user=request.user, asset_id=asset_id)
        return Response(status=status.HTTP_204_NO_CONTENT)


class MediaClipView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(request=MediaClipSerializer, responses={201: MediaAssetSerializer})
    def post(self, request: Request, asset_id: Any) -> Response:
        serializer = MediaClipSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        clip = services.create_clip(
            owner=request.user,
            asset_id=asset_id,
            start=serializer.validated_data["start_seconds"],
            end=serializer.validated_data["end_seconds"],
        )
        return Response(MediaAssetSerializer(clip).data, status=status.HTTP_201_CREATED)


class DirectUploadStartView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(request=MediaDirectStartSerializer, responses={201: MediaDirectSlotSerializer})
    def post(self, request: Request) -> Response:
        serializer = MediaDirectStartSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        row, slot = services.start_direct_upload(owner=request.user, **serializer.validated_data)
        return Response({"upload_id": row.pk, **slot, "expires_at": row.expires_at}, status=status.HTTP_201_CREATED)


class DirectUploadCompleteView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(request=None, responses={201: MediaAssetSerializer})
    def post(self, request: Request, upload_id: Any) -> Response:
        asset = services.complete_direct_upload(owner=request.user, upload_id=upload_id)
        return Response(MediaAssetSerializer(asset).data, status=status.HTTP_201_CREATED)


class MediaFileView(APIView):
    """Stream a rendition behind a signed, expiring link. Supports Range requests (seeking)."""

    permission_classes = [permissions.AllowAny]
    authentication_classes: list[Any] = []

    @extend_schema(responses={(200, "application/octet-stream"): OpenApiTypes.BINARY})
    def get(self, request: Request, token: str) -> HttpResponse:
        asset_id, variant = services.read_token(token)
        asset = MediaAsset.objects.filter(pk=asset_id).first()
        if asset is None or not asset.file:
            raise NotFound()
        fieldfile, mime, size = services.file_for(asset, variant)
        start, end = 0, size - 1
        partial = False
        match = RANGE_RE.match(request.headers.get("Range", ""))
        if match and size:
            first, last = match.groups()
            if first:
                start = int(first)
                end = min(int(last), size - 1) if last else size - 1
            elif last:
                start = max(size - int(last), 0)
            if start > end or start >= size:
                response = HttpResponse(status=416)
                response["Content-Range"] = f"bytes */{size}"
                return response
            partial = True
        handle = fieldfile.open("rb")
        handle.seek(start)
        remaining = end - start + 1

        def stream() -> Any:
            left = remaining
            try:
                while left > 0:
                    chunk = handle.read(min(CHUNK, left))
                    if not chunk:
                        break
                    left -= len(chunk)
                    yield chunk
            finally:
                handle.close()

        response = StreamingHttpResponse(stream(), status=206 if partial else 200, content_type=mime)
        response["Content-Length"] = str(remaining)
        response["Accept-Ranges"] = "bytes"
        if partial:
            response["Content-Range"] = f"bytes {start}-{end}/{size}"
        response["Content-Disposition"] = "inline"
        response["X-Content-Type-Options"] = "nosniff"
        response["Cache-Control"] = "private, max-age=300"
        return response
