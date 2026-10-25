from __future__ import annotations

from typing import Any

from rest_framework import permissions, status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from university.community import selectors, services
from university.community.api.v1 import serializers as s
from university.community.constants import MembershipStatus, Privacy
from university.community.models import CommunityMembership
from university.core.api.pagination import PageNumberPagination
from university.core.api.schema import OpenApiParameter, OpenApiTypes, extend_schema
from university.core.exceptions import AuthenticationFailed, NotFound
from university.permissions.services import authorize


def _context(request: Request, communities: list[Any]) -> dict[str, Any]:
    if not request.user.is_authenticated or not communities:
        return {}
    rows = CommunityMembership.objects.filter(user=request.user, community__in=communities)
    return {"memberships": {m.community_id: m for m in rows}}


def _detail(request: Request, community: Any) -> dict[str, Any]:
    return s.CommunitySerializer(community, context=_context(request, [community])).data


class CommunityListCreateView(APIView):
    permission_classes = [permissions.AllowAny]

    @extend_schema(
        parameters=[OpenApiParameter(p, str) for p in ("q", "kind", "scope_type", "scope_id", "official")],
        responses=s.CommunitySerializer(many=True),
    )
    def get(self, request: Request) -> Response:
        paginator = PageNumberPagination()
        page = paginator.paginate_queryset(selectors.search(request.user, request.query_params), request, view=self)
        return paginator.get_paginated_response(
            s.CommunitySerializer(page, many=True, context=_context(request, page)).data
        )

    @extend_schema(request=s.CommunityCreateSerializer, responses={201: s.CommunitySerializer})
    def post(self, request: Request) -> Response:
        if not request.user.is_authenticated:
            raise AuthenticationFailed()
        serializer = s.CommunityCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        parent_type, parent_id, official = data.pop("parent_type"), data.pop("parent_id"), data.pop("official")
        community = services.create_community(
            creator=request.user, data=data, scope_type=parent_type, scope_id=parent_id, official=official
        )
        return Response(_detail(request, community), status=status.HTTP_201_CREATED)


class CommunityDetailView(APIView):
    permission_classes = [permissions.AllowAny]

    @extend_schema(responses=s.CommunitySerializer)
    def get(self, request: Request, community_id: Any) -> Response:
        return Response(_detail(request, selectors.get_visible_community(request.user, community_id)))

    @extend_schema(request=s.CommunityUpdateSerializer, responses=s.CommunitySerializer)
    def patch(self, request: Request, community_id: Any) -> Response:
        if not request.user.is_authenticated:
            raise AuthenticationFailed()
        serializer = s.CommunityUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        community = services.update_community(
            actor=request.user, community_id=community_id, data=serializer.validated_data
        )
        return Response(_detail(request, community))

    @extend_schema(request=s.CommunityReasonSerializer, responses={204: None})
    def delete(self, request: Request, community_id: Any) -> Response:
        if not request.user.is_authenticated:
            raise AuthenticationFailed()
        services.archive_community(actor=request.user, community_id=community_id, reason=request.data.get("reason", ""))
        return Response(status=status.HTTP_204_NO_CONTENT)


class OfficialView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(request=s.CommunityOfficialSerializer, responses=s.CommunitySerializer)
    def post(self, request: Request, community_id: Any) -> Response:
        serializer = s.CommunityOfficialSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        community = services.set_official(actor=request.user, community_id=community_id, **serializer.validated_data)
        return Response(_detail(request, community))


class JoinView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(request=None, responses=s.CommunityMembershipSerializer)
    def post(self, request: Request, community_id: Any) -> Response:
        member = services.join_community(user=request.user, community_id=community_id)
        return Response(s.CommunityMembershipSerializer(member).data)


class LeaveView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(request=None, responses={204: None})
    def post(self, request: Request, community_id: Any) -> Response:
        services.leave_community(user=request.user, community_id=community_id)
        return Response(status=status.HTTP_204_NO_CONTENT)


class MemberListView(APIView):
    permission_classes = [permissions.AllowAny]

    @extend_schema(parameters=[OpenApiParameter("role", str)], responses=s.CommunityMemberSerializer(many=True))
    def get(self, request: Request, community_id: Any) -> Response:
        community = selectors.get_visible_community(request.user, community_id)
        if community.privacy == Privacy.PRIVATE:
            member = selectors.membership(request.user, community)
            if not (member and member.status == MembershipStatus.ACTIVE) and not services.can_manage_members(
                request.user, community
            ):
                raise NotFound("Community not found.")
        paginator = PageNumberPagination()
        page = paginator.paginate_queryset(selectors.members(community, request.query_params), request, view=self)
        return paginator.get_paginated_response(s.CommunityMemberSerializer(page, many=True).data)


class _ManagerQueueView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    status_filter = MembershipStatus.PENDING

    @extend_schema(responses=s.CommunityMemberSerializer(many=True))
    def get(self, request: Request, community_id: Any) -> Response:
        community = selectors.get_visible_community(request.user, community_id)
        authorize(request.user, "community.members.manage", selectors.scope_of(community))
        qs = CommunityMembership.objects.filter(community=community, status=self.status_filter).select_related("user")
        paginator = PageNumberPagination()
        page = paginator.paginate_queryset(qs.order_by("created_at"), request, view=self)
        return paginator.get_paginated_response(s.CommunityMemberSerializer(page, many=True).data)


class RequestListView(_ManagerQueueView):
    status_filter = MembershipStatus.PENDING


class BanListView(_ManagerQueueView):
    status_filter = MembershipStatus.BANNED


class MemberActionView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    action = "approve"

    @extend_schema(request=s.CommunityReasonSerializer, responses={204: None})
    def post(self, request: Request, community_id: Any, user_id: Any) -> Response:
        reason = str(request.data.get("reason", ""))[:255]
        kwargs = {"actor": request.user, "community_id": community_id, "user_id": user_id}
        if self.action in ("approve", "decline"):
            services.review_request(approve=self.action == "approve", **kwargs)
        elif self.action == "remove":
            services.remove_member(reason=reason, **kwargs)
        elif self.action == "ban":
            services.ban_non_member(reason=reason, **kwargs)
        elif self.action == "unban":
            services.unban(**kwargs)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(request=s.CommunityRoleSerializer, responses=s.CommunityMemberSerializer)
    def patch(self, request: Request, community_id: Any, user_id: Any) -> Response:
        serializer = s.CommunityRoleSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        member = services.change_role(
            actor=request.user, community_id=community_id, user_id=user_id, role=serializer.validated_data["role"]
        )
        return Response(s.CommunityMemberSerializer(member).data)


def member_action(action: str) -> type[MemberActionView]:
    return type(f"Member{action.title()}View", (MemberActionView,), {"action": action})


class TransferView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(request=s.CommunityUserRefSerializer, responses=s.CommunityMemberSerializer)
    def post(self, request: Request, community_id: Any) -> Response:
        serializer = s.CommunityUserRefSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        member = services.transfer_ownership(
            actor=request.user, community_id=community_id, user_id=serializer.validated_data["user_id"]
        )
        return Response(s.CommunityMemberSerializer(member).data)


class InvitationView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(request=s.CommunityUserRefSerializer, responses={201: s.CommunityMemberSerializer})
    def post(self, request: Request, community_id: Any) -> Response:
        serializer = s.CommunityUserRefSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        member = services.invite(
            actor=request.user, community_id=community_id, user_id=serializer.validated_data["user_id"]
        )
        return Response(s.CommunityMemberSerializer(member).data, status=status.HTTP_201_CREATED)


class InvitationResponseView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    accept = True

    @extend_schema(request=None, responses=OpenApiTypes.OBJECT)
    def post(self, request: Request, community_id: Any) -> Response:
        if self.accept:
            member = services.accept_invitation(user=request.user, community_id=community_id)
            return Response(s.CommunityMembershipSerializer(member).data)
        services.decline_invitation(user=request.user, community_id=community_id)
        return Response(status=status.HTTP_204_NO_CONTENT)


class InviteLinkView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(request=s.CommunityInviteLinkCreateSerializer, responses={201: OpenApiTypes.OBJECT})
    def post(self, request: Request, community_id: Any) -> Response:
        serializer = s.CommunityInviteLinkCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        link, code = services.create_invite_link(
            actor=request.user, community_id=community_id, **serializer.validated_data
        )
        return Response(
            {"id": str(link.pk), "code": code, "expires_at": link.expires_at.isoformat(), "max_uses": link.max_uses},
            status=status.HTTP_201_CREATED,
        )


class InviteLinkDetailView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(responses={204: None})
    def delete(self, request: Request, community_id: Any, link_id: Any) -> Response:
        services.revoke_invite_link(actor=request.user, community_id=community_id, link_id=link_id)
        return Response(status=status.HTTP_204_NO_CONTENT)


class JoinWithCodeView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(request=s.CommunityJoinCodeSerializer, responses=s.CommunityMembershipSerializer)
    def post(self, request: Request) -> Response:
        serializer = s.CommunityJoinCodeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        member = services.join_with_code(user=request.user, code=serializer.validated_data["code"])
        return Response(s.CommunityMembershipSerializer(member).data)


class MyCommunitiesView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(responses=s.CommunityMembershipSerializer(many=True))
    def get(self, request: Request) -> Response:
        paginator = PageNumberPagination()
        page = paginator.paginate_queryset(selectors.my_communities(request.user), request, view=self)
        return paginator.get_paginated_response(s.CommunityMembershipSerializer(page, many=True).data)


class MyInvitationsView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(responses=s.CommunityMembershipSerializer(many=True))
    def get(self, request: Request) -> Response:
        qs = CommunityMembership.objects.filter(user=request.user, status=MembershipStatus.INVITED).select_related(
            "community"
        )
        return Response(s.CommunityMembershipSerializer(qs.order_by("-created_at")[:200], many=True).data)
