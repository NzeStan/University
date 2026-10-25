from __future__ import annotations

from typing import Any

from rest_framework import generics, permissions, status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from university.audit.services import record as audit
from university.core.api.pagination import PageNumberPagination
from university.core.api.schema import OpenApiParameter, extend_schema
from university.moderation import selectors, services
from university.moderation.api.v1 import serializers as s
from university.moderation.models import ModerationRule, ReportReason
from university.moderation.services.cases import case_scope
from university.permissions.drf import require_permission
from university.permissions.services import has_permission


# ------------------------------------------------------------------ users
class ReasonListView(generics.ListAPIView):
    permission_classes = [permissions.AllowAny]
    serializer_class = s.ReasonSerializer
    pagination_class = None
    queryset = ReportReason.objects.filter(is_active=True)


class ReportCreateView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(request=s.ReportCreateSerializer, responses={201: s.MyReportSerializer})
    def post(self, request: Request) -> Response:
        serializer = s.ReportCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        report = services.report_content(reporter=request.user, **serializer.validated_data)
        return Response(s.MyReportSerializer(report).data, status=status.HTTP_201_CREATED)


class MyReportsView(generics.ListAPIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = s.MyReportSerializer

    def get_queryset(self) -> Any:
        return selectors.my_reports(self.request.user)


class MyActionsView(generics.ListAPIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = s.MyActionSerializer

    def get_queryset(self) -> Any:
        return selectors.my_actions(self.request.user)


class AppealCreateView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(request=s.AppealCreateSerializer, responses={201: s.MyActionSerializer})
    def post(self, request: Request) -> Response:
        serializer = s.AppealCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        appeal = services.file_appeal(user=request.user, **serializer.validated_data)
        return Response({"id": str(appeal.pk), "status": appeal.status}, status=status.HTTP_201_CREATED)


class MyAppealsView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(responses=s.MyActionSerializer(many=True))
    def get(self, request: Request) -> Response:
        data = [
            {
                "id": str(a.pk),
                "action": a.action.action,
                "content_type": a.action.content_type,
                "object_id": a.action.object_id,
                "status": a.status,
                "decision_reason": a.decision_reason or None,
                "created_at": a.created_at.isoformat(),
            }
            for a in selectors.my_appeals(request.user)[:200]
        ]
        return Response(data)


# -------------------------------------------------------------- moderators
class CaseListView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        parameters=[OpenApiParameter(p, str) for p in ("status", "content_type", "scope_type", "scope_id", "assigned")],
        responses=s.CaseListSerializer(many=True),
    )
    def get(self, request: Request) -> Response:
        paginator = PageNumberPagination()
        page = paginator.paginate_queryset(
            selectors.moderation_queue(request.user, request.query_params), request, view=self
        )
        return paginator.get_paginated_response(s.CaseListSerializer(page, many=True).data)

    @extend_schema(request=s.CaseOpenSerializer, responses={201: s.CaseDetailSerializer})
    def post(self, request: Request) -> Response:
        serializer = s.CaseOpenSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        case = services.open_case(actor=request.user, **serializer.validated_data)
        return Response(s.CaseDetailSerializer(case).data, status=status.HTTP_201_CREATED)


class CaseDetailView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(responses=s.CaseDetailSerializer)
    def get(self, request: Request, case_id: Any) -> Response:
        case = selectors.get_case_for_moderator(request.user, case_id)
        show_reporters = has_permission(request.user, "moderation.reports.view_reporters", case_scope(case))
        if show_reporters:
            audit("moderation.reporters.viewed", actor=request.user, target=case, category="moderation")
        return Response(s.CaseDetailSerializer(case, context={"show_reporters": show_reporters}).data)


class CaseAssignView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(request=None, responses=s.CaseListSerializer)
    def post(self, request: Request, case_id: Any) -> Response:
        return Response(s.CaseListSerializer(services.assign_case(actor=request.user, case_id=case_id)).data)


class CaseActionView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(request=s.ActionCreateSerializer, responses={201: s.ActionSerializer})
    def post(self, request: Request, case_id: Any) -> Response:
        selectors.get_case_for_moderator(request.user, case_id)  # 404/403 before validation detail
        serializer = s.ActionCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        action = services.take_action(actor=request.user, case_id=case_id, **serializer.validated_data)
        return Response(s.ActionSerializer(action).data, status=status.HTTP_201_CREATED)


class AppealQueueView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(parameters=[OpenApiParameter("status", str)], responses=s.AppealSerializer(many=True))
    def get(self, request: Request) -> Response:
        paginator = PageNumberPagination()
        page = paginator.paginate_queryset(
            selectors.appeal_queue(request.user, request.query_params), request, view=self
        )
        return paginator.get_paginated_response(s.AppealSerializer(page, many=True).data)


class AppealDecideView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(request=s.AppealDecisionSerializer, responses=s.AppealSerializer)
    def post(self, request: Request, appeal_id: Any) -> Response:
        serializer = s.AppealDecisionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        appeal = services.decide_appeal(actor=request.user, appeal_id=appeal_id, **serializer.validated_data)
        return Response(s.AppealSerializer(appeal).data)


class RestrictionLiftView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(request=None, responses={204: None})
    def post(self, request: Request, restriction_id: Any) -> Response:
        services.lift_restriction(actor=request.user, restriction_id=restriction_id)
        return Response(status=status.HTTP_204_NO_CONTENT)


class RuleListView(generics.ListAPIView):
    permission_classes = [permissions.IsAuthenticated, require_permission("moderation.rules.manage")]
    serializer_class = s.RuleSerializer
    pagination_class = None
    queryset = ModerationRule.objects.order_by("created_at")


class RuleDetailView(generics.RetrieveUpdateAPIView):
    permission_classes = [permissions.IsAuthenticated, require_permission("moderation.rules.manage")]
    serializer_class = s.RuleSerializer
    queryset = ModerationRule.objects.all()
    lookup_field = "id"
    http_method_names = ["get", "patch", "head", "options"]

    def perform_update(self, serializer: Any) -> None:
        rule = serializer.save()
        audit("moderation.rule.updated", actor=self.request.user, target=rule, category="moderation")
