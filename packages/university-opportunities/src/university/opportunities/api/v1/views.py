from __future__ import annotations

from typing import Any

from django.http import FileResponse
from rest_framework import permissions, status
from rest_framework.parsers import JSONParser, MultiPartParser
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from university.core.api.pagination import PageNumberPagination
from university.core.api.schema import OpenApiParameter, OpenApiTypes, extend_schema, paginated
from university.core.exceptions import NotFound
from university.core.ids import is_valid_uuid
from university.opportunities import selectors, services
from university.opportunities.api.v1 import serializers as s
from university.opportunities.models import Application, Opportunity, SavedOpportunity

FILTERS = [OpenApiParameter(p, str) for p in ("q", "kind", "work_mode", "location", "paid", "institution", "sort")]


def _context(request: Request, opportunities: list[Opportunity]) -> dict[str, Any]:
    user = request.user
    ids = [o.pk for o in opportunities]
    if not user.is_authenticated or not ids:
        return {"viewer": user}
    saved = set(
        SavedOpportunity.objects.filter(user=user, opportunity_id__in=ids).values_list("opportunity_id", flat=True)
    )
    applied = dict(
        Application.objects.filter(applicant=user, opportunity_id__in=ids).values_list("opportunity_id", "status")
    )
    return {"viewer": user, "saved": saved, "applied": applied}


def _page(view: APIView, request: Request, qs: Any) -> Response:
    paginator = PageNumberPagination()
    page = paginator.paginate_queryset(qs, request, view=view)
    return paginator.get_paginated_response(
        s.OpportunitySerializer(page, many=True, context=_context(request, page)).data
    )


def _one(request: Request, opportunity: Opportunity) -> dict[str, Any]:
    return s.OpportunitySerializer(opportunity, context=_context(request, [opportunity])).data


class OpportunityListCreateView(APIView):
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]

    @property
    def throttle_scope(self) -> str | None:  # type: ignore[override]
        return "opportunity_create" if self.request.method == "POST" else None

    @extend_schema(parameters=FILTERS, responses=paginated(s.OpportunitySerializer))
    def get(self, request: Request) -> Response:
        return _page(self, request, selectors.visible_opportunities(request.user, request.query_params))

    @extend_schema(request=s.OpportunityWriteSerializer, responses={201: s.OpportunitySerializer})
    def post(self, request: Request) -> Response:
        serializer = s.OpportunityWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        publish_now = data.pop("publish", False)
        opportunity = services.create_opportunity(actor=request.user, data=data, publish_now=publish_now)
        return Response(_one(request, opportunity), status=status.HTTP_201_CREATED)


class OpportunityDetailView(APIView):
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]

    @extend_schema(responses=s.OpportunitySerializer)
    def get(self, request: Request, opportunity_id: Any) -> Response:
        return Response(_one(request, selectors.get_visible(request.user, opportunity_id)))

    @extend_schema(request=s.OpportunityWriteSerializer, responses=s.OpportunitySerializer)
    def patch(self, request: Request, opportunity_id: Any) -> Response:
        opportunity = selectors.get_visible(request.user, opportunity_id)
        serializer = s.OpportunityWriteSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        data.pop("publish", None)
        opportunity = services.update_opportunity(actor=request.user, opportunity=opportunity, data=data)
        return Response(_one(request, opportunity))

    @extend_schema(responses={204: None})
    def delete(self, request: Request, opportunity_id: Any) -> Response:
        services.delete_opportunity(actor=request.user, opportunity=selectors.get_visible(request.user, opportunity_id))
        return Response(status=status.HTTP_204_NO_CONTENT)


class OpportunityStatusView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(request=s.OpportunityStatusActionSerializer, responses=s.OpportunitySerializer)
    def post(self, request: Request, opportunity_id: Any) -> Response:
        serializer = s.OpportunityStatusActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        opportunity = selectors.get_visible(request.user, opportunity_id)
        opportunity = services.set_status(
            actor=request.user, opportunity=opportunity, action=serializer.validated_data["action"]
        )
        return Response(_one(request, opportunity))


class OpportunityVerifyView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(request=s.OpportunityVerifySerializer, responses=s.OpportunitySerializer)
    def post(self, request: Request, opportunity_id: Any) -> Response:
        serializer = s.OpportunityVerifySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        opportunity = Opportunity.objects.filter(pk=opportunity_id).first() if is_valid_uuid(opportunity_id) else None
        if opportunity is None:
            raise NotFound()
        opportunity = services.verify_poster(
            actor=request.user, opportunity=opportunity, verified=serializer.validated_data["verified"]
        )
        return Response(_one(request, opportunity))


class OpportunityApplyView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [MultiPartParser, JSONParser]
    throttle_scope = "opportunity_apply"

    @extend_schema(
        request={"multipart/form-data": s.OpportunityApplySerializer, "application/json": s.OpportunityApplySerializer},
        responses={201: s.OpportunityApplicationSerializer},
    )
    def post(self, request: Request, opportunity_id: Any) -> Response:
        serializer = s.OpportunityApplySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        opportunity = selectors.get_visible(request.user, opportunity_id)
        application = services.apply(applicant=request.user, opportunity=opportunity, **serializer.validated_data)
        return Response(s.OpportunityApplicationSerializer(application).data, status=status.HTTP_201_CREATED)


class OpportunityApplicationsView(APIView):
    """Applications to your opportunity (posters only)."""

    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        parameters=[OpenApiParameter("status", str)], responses=paginated(s.OpportunityApplicationSerializer)
    )
    def get(self, request: Request, opportunity_id: Any) -> Response:
        opportunity = selectors.get_visible(request.user, opportunity_id)
        if opportunity.poster_id != request.user.pk:
            raise NotFound()
        qs = opportunity.applications.select_related("applicant", "opportunity").order_by("-created_at")
        if request.query_params.get("status"):
            qs = qs.filter(status=request.query_params["status"])
        paginator = PageNumberPagination()
        page = paginator.paginate_queryset(qs, request, view=self)
        return paginator.get_paginated_response(s.OpportunityApplicationSerializer(page, many=True).data)


def _application(request: Request, application_id: Any) -> Application:
    application = (
        Application.objects.select_related("opportunity", "applicant").filter(pk=application_id).first()
        if is_valid_uuid(application_id)
        else None
    )
    if application is None or request.user.pk not in (application.applicant_id, application.opportunity.poster_id):
        raise NotFound()
    return application


class ApplicationDetailView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(responses=s.OpportunityApplicationSerializer)
    def get(self, request: Request, application_id: Any) -> Response:
        return Response(s.OpportunityApplicationSerializer(_application(request, application_id)).data)

    @extend_schema(request=s.OpportunityDecisionSerializer, responses=s.OpportunityApplicationSerializer)
    def patch(self, request: Request, application_id: Any) -> Response:
        serializer = s.OpportunityDecisionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        application = services.decide(
            actor=request.user,
            application=_application(request, application_id),
            status=serializer.validated_data["status"],
        )
        return Response(s.OpportunityApplicationSerializer(application).data)


class ApplicationWithdrawView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(request=None, responses=s.OpportunityApplicationSerializer)
    def post(self, request: Request, application_id: Any) -> Response:
        application = services.withdraw(applicant=request.user, application=_application(request, application_id))
        return Response(s.OpportunityApplicationSerializer(application).data)


class ApplicationResumeView(APIView):
    """The applicant's CV: only the applicant and the poster, never cached."""

    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(responses={(200, "application/pdf"): OpenApiTypes.BINARY})
    def get(self, request: Request, application_id: Any) -> Any:
        application = _application(request, application_id)
        if not application.resume:
            raise NotFound()
        response = FileResponse(application.resume.open("rb"), content_type="application/pdf")
        response["Content-Disposition"] = 'attachment; filename="cv.pdf"'
        response["Cache-Control"] = "private, no-store"
        response["X-Content-Type-Options"] = "nosniff"
        return response


class SaveView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(request=None, responses={204: None})
    def post(self, request: Request, opportunity_id: Any) -> Response:
        services.save(user=request.user, opportunity=selectors.get_visible(request.user, opportunity_id))
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(responses={204: None})
    def delete(self, request: Request, opportunity_id: Any) -> Response:
        services.unsave(user=request.user, opportunity=selectors.get_visible(request.user, opportunity_id))
        return Response(status=status.HTTP_204_NO_CONTENT)


class MyPostedView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(responses=paginated(s.OpportunitySerializer))
    def get(self, request: Request) -> Response:
        return _page(self, request, Opportunity.objects.filter(poster=request.user).order_by("-created_at"))


class MySavedView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(responses=paginated(s.OpportunitySerializer))
    def get(self, request: Request) -> Response:
        ids = SavedOpportunity.objects.filter(user=request.user).values("opportunity_id")
        qs = selectors.visible_opportunities(request.user).filter(pk__in=ids)
        return _page(self, request, qs)


class MyApplicationsView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(responses=paginated(s.OpportunityApplicationSerializer))
    def get(self, request: Request) -> Response:
        qs = (
            Application.objects.filter(applicant=request.user)
            .select_related("opportunity", "applicant")
            .order_by("-created_at")
        )
        paginator = PageNumberPagination()
        page = paginator.paginate_queryset(qs, request, view=self)
        return paginator.get_paginated_response(s.OpportunityApplicationSerializer(page, many=True).data)
