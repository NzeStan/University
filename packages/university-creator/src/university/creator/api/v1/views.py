from __future__ import annotations

import datetime as dt
from typing import Any

from rest_framework import permissions, status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from university.core.api.pagination import PageNumberPagination
from university.core.api.schema import OpenApiParameter, OpenApiTypes, extend_schema
from university.core.context import get_request_context
from university.core.crypto import constant_time_equals
from university.core.exceptions import AuthenticationFailed, NotFound, ValidationError
from university.core.hooks import Hook, hooks
from university.creator import selectors, services
from university.creator.api.v1 import serializers as s
from university.creator.constants import KitVisibility, Metric, OwnershipStatus, RequestStatus
from university.creator.models import CreatorCategory, LinkedAccount, Participation, VerificationRequest
from university.creator.services import analytics
from university.permissions.services import authorize


def _paginate(
    view: APIView, request: Request, items: Any, serializer: Any, context: dict[str, Any] | None = None
) -> Response:
    paginator = PageNumberPagination()
    page = paginator.paginate_queryset(items, request, view=view)
    return paginator.get_paginated_response(serializer(page, many=True, context=context or {"request": request}).data)


def _fingerprint() -> str:
    ctx = get_request_context()
    return f"{ctx.ip_address or ''}|{ctx.user_agent[:200]}"


def _date(value: str | None, field: str) -> dt.date | None:
    if not value:
        return None
    try:
        return dt.date.fromisoformat(value)
    except ValueError:
        raise ValidationError(details={field: ["Use YYYY-MM-DD."]}) from None


def _report(request: Request, profile: Any) -> dict[str, Any]:
    metrics = [m for m in (request.query_params.get("metrics") or "").split(",") if m]
    return analytics.report(
        profile,
        start=_date(request.query_params.get("from"), "from"),
        end=_date(request.query_params.get("to"), "to"),
        metrics=metrics,
    )


ANALYTICS_PARAMS = [OpenApiParameter("from", str), OpenApiParameter("to", str), OpenApiParameter("metrics", str)]


# --------------------------------------------------------------- reference
class CategoryListView(APIView):
    permission_classes = [permissions.AllowAny]

    @extend_schema(responses=s.CreatorCategorySerializer(many=True))
    def get(self, request: Request) -> Response:
        return Response(s.CreatorCategorySerializer(CreatorCategory.objects.filter(is_active=True), many=True).data)


class ProviderListView(APIView):
    permission_classes = [permissions.AllowAny]

    @extend_schema(responses=s.CreatorProviderSerializer(many=True))
    def get(self, request: Request) -> Response:
        return Response(s.provider_list())


# --------------------------------------------------------------- discovery
class CreatorListView(APIView):
    permission_classes = [permissions.AllowAny]

    @extend_schema(
        parameters=[
            OpenApiParameter(p, str)
            for p in ("q", "category", "country", "verified", "open_to_sponsorships", "min_reach")
        ],
        responses=s.CreatorProfileSerializer(many=True),
    )
    def get(self, request: Request) -> Response:
        paginator = PageNumberPagination()
        page = paginator.paginate_queryset(selectors.discover(request.query_params), request, view=self)
        # Blocks depend on the viewer: drop hidden profiles from the page.
        visible = [p for p in page if selectors.can_view_profile(request.user, p)]
        return paginator.get_paginated_response(s.CreatorProfileSerializer(visible, many=True).data)


class CreatorDetailView(APIView):
    permission_classes = [permissions.AllowAny]

    @extend_schema(responses=s.CreatorProfileSerializer)
    def get(self, request: Request, lookup: str) -> Response:
        profile = selectors.get_visible_profile(request.user, lookup)
        analytics.record_view(profile, request.user, Metric.PROFILE_VIEWS, fingerprint=_fingerprint())
        return Response(s.CreatorProfileSerializer(profile).data)


def _platform_stats(profile: Any, viewer: Any) -> dict[str, Any]:
    social = hooks.collect(Hook.USER_PUBLIC_PROFILE, profile.user, viewer).get("social") or {}
    return {
        "platform_followers": social.get("followers_count"),
        "platform_posts": social.get("posts_count"),
        "verified_reach": profile.verified_reach,
    }


class CreatorMediaKitView(APIView):
    permission_classes = [permissions.AllowAny]

    @extend_schema(parameters=[OpenApiParameter("token", str)], responses=s.CreatorMediaKitSerializer)
    def get(self, request: Request, lookup: str) -> Response:
        profile = selectors.get_visible_profile(request.user, lookup)
        kit = services.get_media_kit(profile)
        is_owner = request.user.is_authenticated and request.user.pk == profile.user_id
        token = request.query_params.get("token") or ""
        allowed = (
            is_owner
            or kit.visibility == KitVisibility.PUBLIC
            or (kit.visibility == KitVisibility.UNLISTED and token and constant_time_equals(token, kit.share_token))
        )
        if not allowed:
            raise NotFound("Media kit not found.")
        analytics.record_view(profile, request.user, Metric.MEDIA_KIT_VIEWS, fingerprint=_fingerprint())
        context = {"platform_stats": _platform_stats(profile, request.user)}
        return Response(s.CreatorMediaKitSerializer(kit, context=context).data)


# ------------------------------------------------------------- own profile
class MyCreatorProfileView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(responses=s.CreatorOwnProfileSerializer)
    def get(self, request: Request) -> Response:
        return Response(s.CreatorOwnProfileSerializer(selectors.own_profile(request.user)).data)

    @extend_schema(request=s.CreatorProfileWriteSerializer, responses={201: s.CreatorOwnProfileSerializer})
    def post(self, request: Request) -> Response:
        serializer = s.CreatorProfileWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        categories = data.pop("categories", [])
        data.pop("status", None)
        profile = services.create_profile(user=request.user, data=data, categories=categories)
        return Response(s.CreatorOwnProfileSerializer(profile).data, status=status.HTTP_201_CREATED)

    @extend_schema(request=s.CreatorProfileWriteSerializer, responses=s.CreatorOwnProfileSerializer)
    def patch(self, request: Request) -> Response:
        serializer = s.CreatorProfileWriteSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        categories = data.pop("categories", None)
        profile = services.update_profile(user=request.user, data=data, categories=categories)
        return Response(s.CreatorOwnProfileSerializer(profile).data)


class MyLinkedAccountsView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(responses=s.CreatorOwnLinkedAccountSerializer(many=True))
    def get(self, request: Request) -> Response:
        accounts = selectors.own_profile(request.user).linked_accounts.order_by("provider", "handle")
        return Response(s.CreatorOwnLinkedAccountSerializer(accounts, many=True).data)

    @extend_schema(request=s.CreatorLinkAccountSerializer, responses={201: s.CreatorOwnLinkedAccountSerializer})
    def post(self, request: Request) -> Response:
        serializer = s.CreatorLinkAccountSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        account = services.link_account(user=request.user, **serializer.validated_data)
        return Response(s.CreatorOwnLinkedAccountSerializer(account).data, status=status.HTTP_201_CREATED)


class MyLinkedAccountDetailView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(request=s.CreatorAccountUpdateSerializer, responses=s.CreatorOwnLinkedAccountSerializer)
    def patch(self, request: Request, account_id: Any) -> Response:
        serializer = s.CreatorAccountUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        account = services.update_account(user=request.user, account_id=account_id, **serializer.validated_data)
        return Response(s.CreatorOwnLinkedAccountSerializer(account).data)

    @extend_schema(responses={204: None})
    def delete(self, request: Request, account_id: Any) -> Response:
        services.unlink_account(user=request.user, account_id=account_id)
        return Response(status=status.HTTP_204_NO_CONTENT)


class MyLinkedAccountVerifyView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(request=None, responses=s.CreatorOwnLinkedAccountSerializer)
    def post(self, request: Request, account_id: Any) -> Response:
        account = services.verify_account(user=request.user, account_id=account_id)
        return Response(s.CreatorOwnLinkedAccountSerializer(account).data)


class MyVerificationView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(responses=s.CreatorVerificationRequestSerializer)
    def get(self, request: Request) -> Response:
        latest = selectors.own_profile(request.user).verification_requests.order_by("-created_at").first()
        if latest is None:
            raise NotFound("No verification request yet.")
        return Response(s.CreatorVerificationRequestSerializer(latest).data)

    @extend_schema(
        request=s.CreatorVerificationCreateSerializer, responses={201: s.CreatorVerificationRequestSerializer}
    )
    def post(self, request: Request) -> Response:
        serializer = s.CreatorVerificationCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        req = services.request_verification(user=request.user, **serializer.validated_data)
        return Response(s.CreatorVerificationRequestSerializer(req).data, status=status.HTTP_201_CREATED)

    @extend_schema(responses={204: None})
    def delete(self, request: Request) -> Response:
        services.withdraw_verification(user=request.user)
        return Response(status=status.HTTP_204_NO_CONTENT)


class MyMediaKitView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def _respond(self, request: Request, kit: Any) -> Response:
        context = {"platform_stats": _platform_stats(kit.profile, request.user)}
        return Response(s.CreatorOwnMediaKitSerializer(kit, context=context).data)

    @extend_schema(responses=s.CreatorOwnMediaKitSerializer)
    def get(self, request: Request) -> Response:
        return self._respond(request, services.get_media_kit(selectors.own_profile(request.user)))

    @extend_schema(request=s.CreatorMediaKitWriteSerializer, responses=s.CreatorOwnMediaKitSerializer)
    def patch(self, request: Request) -> Response:
        serializer = s.CreatorMediaKitWriteSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        return self._respond(request, services.update_media_kit(user=request.user, data=serializer.validated_data))


class MyMediaKitRotateView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(request=None, responses=s.CreatorOwnMediaKitSerializer)
    def post(self, request: Request) -> Response:
        kit = services.rotate_share_token(user=request.user)
        return Response(s.CreatorOwnMediaKitSerializer(kit, context={"platform_stats": None}).data)


class MyAnalyticsView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(parameters=ANALYTICS_PARAMS, responses=OpenApiTypes.OBJECT)
    def get(self, request: Request) -> Response:
        return Response(_report(request, selectors.own_profile(request.user)))


class CreatorAnalyticsView(APIView):
    """Support staff only (``creator.analytics.view``)."""

    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(parameters=ANALYTICS_PARAMS, responses=OpenApiTypes.OBJECT)
    def get(self, request: Request, profile_id: Any) -> Response:
        authorize(request.user, "creator.analytics.view", audit_denial=True)
        return Response(_report(request, selectors.get_profile(profile_id)))


# ----------------------------------------------------------------- reviews
class VerificationQueueView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        parameters=[OpenApiParameter("status", str)], responses=s.CreatorVerificationRequestSerializer(many=True)
    )
    def get(self, request: Request) -> Response:
        authorize(request.user, "creator.verify")
        wanted = request.query_params.get("status") or RequestStatus.PENDING
        qs = VerificationRequest.objects.filter(status=wanted).select_related("profile__user").order_by("created_at")
        return _paginate(self, request, qs, s.CreatorVerificationRequestSerializer)


class VerificationDecisionView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    approve = True

    @extend_schema(request=s.CreatorReasonSerializer, responses=s.CreatorVerificationRequestSerializer)
    def post(self, request: Request, request_id: Any) -> Response:
        serializer = s.CreatorReasonSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        req = services.decide_verification(
            actor=request.user, request_id=request_id, approve=self.approve, reason=serializer.validated_data["reason"]
        )
        return Response(s.CreatorVerificationRequestSerializer(req).data)


class AccountReviewQueueView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(responses=s.CreatorOwnLinkedAccountSerializer(many=True))
    def get(self, request: Request) -> Response:
        authorize(request.user, "creator.verify")
        qs = LinkedAccount.objects.filter(ownership=OwnershipStatus.PENDING_REVIEW).order_by("created_at")
        return _paginate(self, request, qs, s.CreatorOwnLinkedAccountSerializer)


class AccountConfirmView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(request=s.CreatorConfirmAccountSerializer, responses=s.CreatorOwnLinkedAccountSerializer)
    def post(self, request: Request, account_id: Any) -> Response:
        serializer = s.CreatorConfirmAccountSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        account = services.confirm_account(actor=request.user, account_id=account_id, **serializer.validated_data)
        return Response(s.CreatorOwnLinkedAccountSerializer(account).data)


class RevokeVerificationView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(request=s.CreatorReasonSerializer, responses=s.CreatorProfileSerializer)
    def post(self, request: Request, profile_id: Any) -> Response:
        serializer = s.CreatorReasonSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        profile = services.revoke_verification(
            actor=request.user, profile_id=profile_id, reason=serializer.validated_data["reason"]
        )
        return Response(s.CreatorProfileSerializer(profile).data)


# --------------------------------------------------------------- campaigns
def _campaign_context(request: Request, campaigns: Any) -> dict[str, Any]:
    campaigns = list(campaigns)
    context: dict[str, Any] = {"request": request}
    if request.user.is_authenticated and campaigns:
        context["managed"] = {c.pk: selectors.can_manage_campaign(request.user, c) for c in campaigns}
        context["participations"] = {
            p.campaign_id: p for p in Participation.objects.filter(profile__user=request.user, campaign__in=campaigns)
        }
    return context


def _campaign(request: Request, campaign: Any) -> dict[str, Any]:
    return s.CreatorCampaignSerializer(campaign, context=_campaign_context(request, [campaign])).data


class CampaignListCreateView(APIView):
    permission_classes = [permissions.AllowAny]

    @extend_schema(
        parameters=[OpenApiParameter("q", str), OpenApiParameter("category", str)],
        responses=s.CreatorCampaignSerializer(many=True),
    )
    def get(self, request: Request) -> Response:
        paginator = PageNumberPagination()
        page = paginator.paginate_queryset(selectors.open_campaigns(request.query_params), request, view=self)
        return paginator.get_paginated_response(
            s.CreatorCampaignSerializer(page, many=True, context=_campaign_context(request, page)).data
        )

    @extend_schema(request=s.CreatorCampaignWriteSerializer, responses={201: s.CreatorCampaignSerializer})
    def post(self, request: Request) -> Response:
        if not request.user.is_authenticated:
            raise AuthenticationFailed()
        serializer = s.CreatorCampaignWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        categories = data.pop("categories", [])
        sponsor_type, sponsor_id = data.pop("sponsor_type"), data.pop("sponsor_id")
        campaign = services.create_campaign(
            owner=request.user, data=data, categories=categories, scope_type=sponsor_type, scope_id=sponsor_id
        )
        return Response(_campaign(request, campaign), status=status.HTTP_201_CREATED)


class CampaignDetailView(APIView):
    permission_classes = [permissions.AllowAny]

    @extend_schema(responses=s.CreatorCampaignSerializer)
    def get(self, request: Request, campaign_id: Any) -> Response:
        return Response(_campaign(request, selectors.get_visible_campaign(request.user, campaign_id)))

    @extend_schema(request=s.CreatorCampaignWriteSerializer, responses=s.CreatorCampaignSerializer)
    def patch(self, request: Request, campaign_id: Any) -> Response:
        selectors.get_visible_campaign(request.user, campaign_id)
        serializer = s.CreatorCampaignWriteSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        data = {k: v for k, v in serializer.validated_data.items() if k not in ("sponsor_type", "sponsor_id")}
        categories = data.pop("categories", None)
        campaign = services.update_campaign(
            actor=request.user, campaign_id=campaign_id, data=data, categories=categories
        )
        return Response(_campaign(request, campaign))


def campaign_action(name: str) -> type[APIView]:
    action = {
        "publish": services.publish_campaign,
        "close": services.close_campaign,
        "complete": services.complete_campaign,
    }.get(name)

    class CampaignActionView(APIView):
        permission_classes = [permissions.IsAuthenticated]

        @extend_schema(
            request=s.CreatorReasonSerializer,
            responses=s.CreatorCampaignSerializer,
            operation_id=f"creator_campaign_{name}",
        )
        def post(self, request: Request, campaign_id: Any) -> Response:
            selectors.get_visible_campaign(request.user, campaign_id)
            if action is None:
                serializer = s.CreatorReasonSerializer(data=request.data)
                serializer.is_valid(raise_exception=True)
                campaign = services.cancel_campaign(
                    actor=request.user, campaign_id=campaign_id, reason=serializer.validated_data["reason"]
                )
            else:
                campaign = action(actor=request.user, campaign_id=campaign_id)
            return Response(_campaign(request, campaign))

    CampaignActionView.__name__ = f"Campaign{name.title()}View"
    return CampaignActionView


class CampaignParticipationsView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(parameters=[OpenApiParameter("status", str)], responses=s.CreatorParticipationSerializer(many=True))
    def get(self, request: Request, campaign_id: Any) -> Response:
        campaign = selectors.get_visible_campaign(request.user, campaign_id)
        if not selectors.can_manage_campaign(request.user, campaign):
            raise NotFound("Campaign not found.")
        qs = campaign.participations.select_related("profile__user", "campaign").order_by("status", "created_at")
        if wanted := request.query_params.get("status"):
            qs = qs.filter(status=wanted)
        return _paginate(self, request, qs, s.CreatorParticipationSerializer)


class CampaignApplyView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(request=s.CreatorApplySerializer, responses={201: s.CreatorParticipationSerializer})
    def post(self, request: Request, campaign_id: Any) -> Response:
        serializer = s.CreatorApplySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        participation = services.apply(user=request.user, campaign_id=campaign_id, **serializer.validated_data)
        return Response(s.CreatorParticipationSerializer(participation).data, status=status.HTTP_201_CREATED)


class CampaignInviteView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(request=s.CreatorInviteSerializer, responses={201: s.CreatorParticipationSerializer})
    def post(self, request: Request, campaign_id: Any) -> Response:
        selectors.get_visible_campaign(request.user, campaign_id)
        serializer = s.CreatorInviteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        participation = services.invite(actor=request.user, campaign_id=campaign_id, **serializer.validated_data)
        return Response(s.CreatorParticipationSerializer(participation).data, status=status.HTTP_201_CREATED)


def _visible_participation(user: Any, participation_id: Any) -> Participation:
    participation = (
        Participation.objects.select_related("profile__user", "campaign").filter(pk=participation_id).first()
    )
    if participation is None or not (
        participation.profile.user_id == user.pk or selectors.can_manage_campaign(user, participation.campaign)
    ):
        raise NotFound("Participation not found.")
    return participation


class ParticipationDecisionView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(request=s.CreatorDecisionSerializer, responses=s.CreatorParticipationSerializer)
    def post(self, request: Request, participation_id: Any) -> Response:
        participation = _visible_participation(request.user, participation_id)
        serializer = s.CreatorDecisionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        if participation.profile.user_id == request.user.pk:
            result = services.creator_decision(
                user=request.user, participation_id=participation_id, action=data["action"], note=data["note"]
            )
        else:
            result = services.brand_decision(
                actor=request.user,
                participation_id=participation_id,
                action=data["action"],
                fee_minor=data.get("fee_minor"),
                note=data["note"],
            )
        return Response(s.CreatorParticipationSerializer(result).data)


class DeliverableListView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(responses=s.CreatorDeliverableSerializer(many=True))
    def get(self, request: Request, participation_id: Any) -> Response:
        participation = _visible_participation(request.user, participation_id)
        return Response(s.CreatorDeliverableSerializer(participation.deliverables.all(), many=True).data)

    @extend_schema(request=s.CreatorDeliverableWriteSerializer, responses={201: s.CreatorDeliverableSerializer})
    def post(self, request: Request, participation_id: Any) -> Response:
        _visible_participation(request.user, participation_id)
        serializer = s.CreatorDeliverableWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        deliverable = services.add_deliverable(
            actor=request.user, participation_id=participation_id, data=serializer.validated_data
        )
        return Response(s.CreatorDeliverableSerializer(deliverable).data, status=status.HTTP_201_CREATED)


class DeliverableSubmitView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(request=s.CreatorSubmitSerializer, responses=s.CreatorDeliverableSerializer)
    def post(self, request: Request, deliverable_id: Any) -> Response:
        serializer = s.CreatorSubmitSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        deliverable = services.submit_deliverable(
            user=request.user, deliverable_id=deliverable_id, **serializer.validated_data
        )
        return Response(s.CreatorDeliverableSerializer(deliverable).data)


class DeliverableReviewView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(request=s.CreatorReviewSerializer, responses=s.CreatorDeliverableSerializer)
    def post(self, request: Request, deliverable_id: Any) -> Response:
        serializer = s.CreatorReviewSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        deliverable = services.review_deliverable(
            actor=request.user, deliverable_id=deliverable_id, **serializer.validated_data
        )
        return Response(s.CreatorDeliverableSerializer(deliverable).data)


class MyParticipationsView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(responses=s.CreatorParticipationSerializer(many=True))
    def get(self, request: Request) -> Response:
        qs = selectors.my_participations(request.user).select_related("profile__user")
        return _paginate(self, request, qs, s.CreatorParticipationSerializer)


class MyCampaignsView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(responses=s.CreatorCampaignSerializer(many=True))
    def get(self, request: Request) -> Response:
        paginator = PageNumberPagination()
        page = paginator.paginate_queryset(selectors.managed_campaigns(request.user), request, view=self)
        return paginator.get_paginated_response(
            s.CreatorCampaignSerializer(page, many=True, context=_campaign_context(request, page)).data
        )
