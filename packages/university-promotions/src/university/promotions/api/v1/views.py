from __future__ import annotations

from typing import Any

from rest_framework import permissions, status
from rest_framework.parsers import MultiPartParser
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from university.core.api.pagination import PageNumberPagination
from university.core.api.schema import OpenApiParameter, extend_schema, paginated
from university.core.http import get_client_ip, get_user_agent
from university.permissions.drf import require_permission
from university.promotions import services
from university.promotions.api.v1 import serializers as s
from university.promotions.conf import promotions_settings
from university.promotions.models import Campaign, CampaignStatus


class OptionsView(APIView):
    permission_classes = [permissions.AllowAny]

    @extend_schema(responses=s.PromotionOptionsSerializer)
    def get(self, request: Request) -> Response:
        return Response(
            {
                "placements": promotions_settings.get("PLACEMENTS"),
                "boostable": promotions_settings.get("BOOSTABLE"),
                "cpm_minor": promotions_settings.get("CPM_MINOR"),
                "min_budget_minor": promotions_settings.get("MIN_BUDGET_MINOR"),
                "require_payment": bool(promotions_settings.get("REQUIRE_PAYMENT")),
            }
        )


class CampaignListCreateView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(responses=paginated(s.PromotionCampaignSerializer))
    def get(self, request: Request) -> Response:
        paginator = PageNumberPagination()
        page = paginator.paginate_queryset(
            Campaign.objects.filter(advertiser=request.user).order_by("-created_at"), request, view=self
        )
        return paginator.get_paginated_response(s.PromotionCampaignSerializer(page, many=True).data)

    @extend_schema(request=s.PromotionCampaignWriteSerializer, responses={201: s.PromotionCampaignSerializer})
    def post(self, request: Request) -> Response:
        serializer = s.PromotionCampaignWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        campaign = services.create_campaign(actor=request.user, data=dict(serializer.validated_data))
        return Response(s.PromotionCampaignSerializer(campaign).data, status=status.HTTP_201_CREATED)


class CampaignDetailView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(responses=s.PromotionCampaignSerializer)
    def get(self, request: Request, campaign_id: Any) -> Response:
        return Response(s.PromotionCampaignSerializer(services._own(request.user, campaign_id)).data)

    @extend_schema(request=s.PromotionCampaignWriteSerializer, responses=s.PromotionCampaignSerializer)
    def patch(self, request: Request, campaign_id: Any) -> Response:
        serializer = s.PromotionCampaignWriteSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        campaign = services.update_campaign(
            actor=request.user, campaign_id=campaign_id, data=dict(serializer.validated_data)
        )
        return Response(s.PromotionCampaignSerializer(campaign).data)


class CampaignImageView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [MultiPartParser]
    throttle_scope = "upload"

    @extend_schema(request={"multipart/form-data": s.PromotionImageSerializer}, responses=s.PromotionCampaignSerializer)
    def post(self, request: Request, campaign_id: Any) -> Response:
        serializer = s.PromotionImageSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        campaign = services.set_image(
            actor=request.user, campaign_id=campaign_id, file=serializer.validated_data["file"]
        )
        return Response(s.PromotionCampaignSerializer(campaign).data)


class _CampaignActionView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    operation = "submit"

    @extend_schema(request=None, responses=s.PromotionCampaignSerializer)
    def post(self, request: Request, campaign_id: Any) -> Response:
        if self.operation == "submit":
            campaign = services.submit(actor=request.user, campaign_id=campaign_id)
        else:
            campaign = services.set_paused(
                actor=request.user, campaign_id=campaign_id, paused=self.operation == "pause"
            )
        return Response(s.PromotionCampaignSerializer(campaign).data)


class SubmitView(_CampaignActionView):
    operation = "submit"


class PauseView(_CampaignActionView):
    operation = "pause"


class ResumeView(_CampaignActionView):
    operation = "resume"


class StatsView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(responses=s.PromotionStatsSerializer)
    def get(self, request: Request, campaign_id: Any) -> Response:
        return Response(services.stats(actor=request.user, campaign_id=campaign_id))


class ReviewQueueView(APIView):
    permission_classes = [permissions.IsAuthenticated, require_permission("promotions.review")]

    @extend_schema(responses=paginated(s.PromotionCampaignSerializer))
    def get(self, request: Request) -> Response:
        paginator = PageNumberPagination()
        qs = Campaign.objects.filter(status=CampaignStatus.IN_REVIEW).order_by("created_at")
        page = paginator.paginate_queryset(qs, request, view=self)
        return paginator.get_paginated_response(s.PromotionCampaignSerializer(page, many=True).data)


class ReviewView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(request=s.PromotionReviewSerializer, responses=s.PromotionCampaignSerializer)
    def post(self, request: Request, campaign_id: Any) -> Response:
        serializer = s.PromotionReviewSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        campaign = services.review(actor=request.user, campaign_id=campaign_id, **serializer.validated_data)
        return Response(s.PromotionCampaignSerializer(campaign).data)


class ServeView(APIView):
    """Sponsored items for a placement. Show each with its "Sponsored" label."""

    permission_classes = [permissions.AllowAny]
    throttle_scope = "promotions_serve"

    @extend_schema(
        parameters=[OpenApiParameter("placement", str, required=True)], responses=s.PromotedItemSerializer(many=True)
    )
    def get(self, request: Request) -> Response:
        fingerprint = f"{get_client_ip(request)}|{get_user_agent(request)}"
        served = services.serve(
            viewer=request.user, placement=request.query_params.get("placement", ""), fingerprint=fingerprint
        )
        items = [
            {"token": token, "campaign_id": c.pk, "kind": c.kind, "label": "Sponsored", "campaign": c}
            for c, token in served
        ]
        return Response(s.PromotedItemSerializer(items, many=True).data)


class ImpressionView(APIView):
    permission_classes = [permissions.AllowAny]
    throttle_scope = "promotions_track"

    @extend_schema(request=s.PromotionTokenSerializer, responses={204: None})
    def post(self, request: Request) -> Response:
        serializer = s.PromotionTokenSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.record_impression(serializer.validated_data["token"])
        return Response(status=status.HTTP_204_NO_CONTENT)


class ClickView(APIView):
    permission_classes = [permissions.AllowAny]
    throttle_scope = "promotions_track"

    @extend_schema(request=s.PromotionTokenSerializer, responses=s.PromotionClickResultSerializer)
    def post(self, request: Request) -> Response:
        serializer = s.PromotionTokenSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        campaign = services.record_click(serializer.validated_data["token"])
        if campaign is None:
            return Response({"destination_url": None, "content": None})
        if campaign.kind == "ad":
            return Response({"destination_url": campaign.destination_url, "content": None})
        return Response({"destination_url": None, "content": {"type": campaign.content_type, "id": campaign.object_id}})
