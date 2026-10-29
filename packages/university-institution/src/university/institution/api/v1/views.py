from __future__ import annotations

from typing import Any

from django.db import models
from django.http import FileResponse
from rest_framework import generics, permissions, status
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from university.audit.services import record as audit
from university.core.api.pagination import PageNumberPagination
from university.core.api.schema import OpenApiParameter, OpenApiTypes, extend_schema, extend_schema_view, paginated
from university.core.exceptions import NotFound, ValidationError
from university.core.ids import is_valid_uuid
from university.institution import selectors, services
from university.institution.api.v1 import serializers as s
from university.institution.models import (
    AcademicSession,
    AcademicUnit,
    Announcement,
    Campus,
    Institution,
    InstitutionMembership,
    InstitutionType,
    Level,
    Programme,
    VerificationRequest,
)
from university.institution.services import announcements
from university.institution.services.common import institution_scope
from university.permissions.drf import require_permission
from university.permissions.services import authorize

#: ``<field>_id`` payload keys and the models they must resolve to.
REFERENCES: dict[str, tuple[str, type[models.Model]]] = {
    "parent_id": ("parent", AcademicUnit),
    "campus_id": ("campus", Campus),
    "academic_unit_id": ("academic_unit", AcademicUnit),
    "programme_id": ("programme", Programme),
    "level_id": ("level", Level),
    "campus": ("campus", Campus),
    "academic_unit": ("academic_unit", AcademicUnit),
    "programme": ("programme", Programme),
    "level": ("level", Level),
}


def resolve_references(institution: Institution, data: dict[str, Any]) -> dict[str, Any]:
    """Replace UUID references with objects *of this institution* only."""
    resolved = dict(data)
    for key in [k for k in data if k in REFERENCES]:
        field, model = REFERENCES[key]
        value = resolved.pop(key)
        if value is None:
            resolved[field] = None
            continue
        obj = model.objects.filter(pk=value, institution=institution).first()
        if obj is None:
            raise ValidationError(details={field: ["Not found in this institution."]})
        resolved[field] = obj
    return resolved


class InstitutionMixin:
    """Resolves ``institution_id`` from the URL (404 when not visible)."""

    kwargs: dict[str, Any]
    request: Request

    def get_institution(self) -> Institution:
        if not hasattr(self, "_institution"):
            self._institution = selectors.get_institution(self.kwargs["institution_id"], user=self.request.user)
        return self._institution


# ------------------------------------------------------------ institutions
class InstitutionTypeListView(generics.ListAPIView):
    permission_classes = [permissions.AllowAny]
    serializer_class = s.InstitutionTypeSerializer
    pagination_class = None
    queryset = InstitutionType.objects.filter(is_active=True)


class InstitutionListCreateView(generics.ListCreateAPIView):
    serializer_class = s.InstitutionSerializer
    pagination_class = PageNumberPagination

    def get_permissions(self) -> list[Any]:
        if self.request.method == "POST":
            return [permissions.IsAuthenticated(), require_permission("institution.manage")()]
        return [permissions.AllowAny()]

    @extend_schema(
        parameters=[
            OpenApiParameter("country", str, description="ISO 3166-1 alpha-2"),
            OpenApiParameter("type", str),
            OpenApiParameter("q", str, description="Search name, short name or city"),
            OpenApiParameter("verified", bool),
        ]
    )
    def get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().get(request, *args, **kwargs)

    def get_queryset(self) -> Any:
        return selectors.list_institutions(self.request.query_params)

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        institution = services.create_institution(actor=request.user, data=serializer.validated_data)
        return Response(self.get_serializer(institution).data, status=status.HTTP_201_CREATED)


class InstitutionDetailView(InstitutionMixin, APIView):
    permission_classes = [permissions.AllowAny]

    @extend_schema(responses=s.InstitutionSerializer)
    def get(self, request: Request, institution_id: Any) -> Response:
        return Response(s.InstitutionSerializer(self.get_institution()).data)

    @extend_schema(request=s.InstitutionSerializer, responses=s.InstitutionSerializer)
    def patch(self, request: Request, institution_id: Any) -> Response:
        if not request.user.is_authenticated:
            raise NotFound("Institution not found.")
        institution = self.get_institution()
        serializer = s.InstitutionSerializer(institution, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        services.update_institution(actor=request.user, institution=institution, data=serializer.validated_data)
        return Response(s.InstitutionSerializer(institution).data)


class DomainListCreateView(InstitutionMixin, APIView):
    permission_classes = [permissions.AllowAny]

    @extend_schema(responses=s.DomainSerializer(many=True))
    def get(self, request: Request, institution_id: Any) -> Response:
        institution = self.get_institution()
        qs = institution.domains.all()
        if not (
            request.user.is_authenticated
            and selectors.can_manage(request.user, institution, "institution.domains.manage")
        ):
            qs = qs.filter(is_verified=True)
        return Response(s.DomainSerializer(qs, many=True).data)

    @extend_schema(request=s.DomainSerializer, responses={201: s.DomainSerializer})
    def post(self, request: Request, institution_id: Any) -> Response:
        if not request.user.is_authenticated:
            raise NotFound("Institution not found.")
        serializer = s.DomainSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        domain = services.add_domain(
            actor=request.user,
            institution=self.get_institution(),
            domain=serializer.validated_data["domain"],
            allow_subdomains=serializer.validated_data.get("allow_subdomains", False),
        )
        return Response(s.DomainSerializer(domain).data, status=status.HTTP_201_CREATED)


class DomainDetailView(InstitutionMixin, APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(responses={204: None})
    def delete(self, request: Request, institution_id: Any, domain_id: Any) -> Response:
        services.remove_domain(actor=request.user, institution=self.get_institution(), domain_id=domain_id)
        return Response(status=status.HTTP_204_NO_CONTENT)


# --------------------------------------------------------------- structure
class StructureListCreateView(InstitutionMixin, APIView):
    """Public list + scoped create for one kind of academic structure."""

    permission_classes = [permissions.AllowAny]
    serializer_class: type = s.CampusSerializer
    kind: str = "campus"

    def list_queryset(self, institution: Institution) -> Any:
        params = self.request.query_params
        return {
            "campus": lambda: selectors.campuses(institution),
            "unit": lambda: selectors.academic_units(institution, params),
            "programme": lambda: selectors.programmes(institution, params),
            "level": lambda: selectors.levels(institution, params),
            "session": lambda: selectors.sessions(institution),
        }[self.kind]()

    def get(self, request: Request, institution_id: Any) -> Response:
        queryset = self.list_queryset(self.get_institution())
        return Response(self.serializer_class(queryset[:1000], many=True).data)

    def post(self, request: Request, institution_id: Any) -> Response:
        if not request.user.is_authenticated:
            raise NotFound("Institution not found.")
        institution = self.get_institution()
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = resolve_references(institution, dict(serializer.validated_data))
        actor = request.user
        if self.kind == "campus":
            obj = services.create_campus(actor=actor, institution=institution, data=data)
        elif self.kind == "unit":
            obj = services.create_academic_unit(actor=actor, institution=institution, data=data)
        elif self.kind == "programme":
            obj = services.create_programme(actor=actor, institution=institution, data=data)
        elif self.kind == "level":
            obj = services.create_level(actor=actor, institution=institution, data=data)
        else:
            make_current = data.pop("make_current", False)
            obj = services.create_session(actor=actor, institution=institution, data=data, make_current=make_current)
        return Response(self.serializer_class(obj).data, status=status.HTTP_201_CREATED)


def structure_view(kind: str, serializer: type) -> type[StructureListCreateView]:
    attrs = {"kind": kind, "serializer_class": serializer}
    view = type(f"{kind.title()}ListCreateView", (StructureListCreateView,), attrs)
    return extend_schema_view(
        get=extend_schema(responses=serializer(many=True)),
        post=extend_schema(request=serializer, responses={201: serializer}),
    )(view)


STRUCTURE_MODELS: dict[str, tuple[type[models.Model], type]] = {
    "campuses": (Campus, s.CampusSerializer),
    "units": (AcademicUnit, s.AcademicUnitSerializer),
    "programmes": (Programme, s.ProgrammeSerializer),
    "levels": (Level, s.LevelSerializer),
    "sessions": (AcademicSession, s.AcademicSessionSerializer),
}


class StructureDetailView(InstitutionMixin, APIView):
    permission_classes = [permissions.AllowAny]

    def _object(self, kind: str, object_id: Any) -> tuple[models.Model, type]:
        if kind not in STRUCTURE_MODELS or not is_valid_uuid(object_id):
            raise NotFound()
        model, serializer = STRUCTURE_MODELS[kind]
        obj = model.objects.filter(pk=object_id, institution=self.get_institution()).first()
        if obj is None:
            raise NotFound()
        return obj, serializer

    @extend_schema(operation_id="institution_structure_retrieve", responses=OpenApiTypes.OBJECT)
    def get(self, request: Request, institution_id: Any, kind: str, object_id: Any) -> Response:
        obj, serializer = self._object(kind, object_id)
        return Response(serializer(obj).data)

    @extend_schema(
        operation_id="institution_structure_partial_update",
        request=OpenApiTypes.OBJECT,
        responses=OpenApiTypes.OBJECT,
    )
    def patch(self, request: Request, institution_id: Any, kind: str, object_id: Any) -> Response:
        if not request.user.is_authenticated:
            raise NotFound()
        obj, serializer_class = self._object(kind, object_id)
        serializer = serializer_class(obj, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        data = resolve_references(self.get_institution(), dict(serializer.validated_data))
        make_current = data.pop("make_current", False)
        data.pop("slug", None)
        services.update_structure(actor=request.user, instance=obj, data=data)
        if make_current and isinstance(obj, AcademicSession):
            services.set_current_session(actor=request.user, session=obj)
        return Response(serializer_class(obj).data)


class SemesterCreateView(InstitutionMixin, APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(request=s.SemesterSerializer, responses={201: s.SemesterSerializer})
    def post(self, request: Request, institution_id: Any, session_id: Any) -> Response:
        session = AcademicSession.objects.filter(pk=session_id, institution=self.get_institution()).first()
        if session is None:
            raise NotFound()
        serializer = s.SemesterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        semester = services.create_semester(actor=request.user, session=session, data=dict(serializer.validated_data))
        return Response(s.SemesterSerializer(semester).data, status=status.HTTP_201_CREATED)


# ----------------------------------------------------------- my memberships
class MyMembershipListCreateView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @property
    def throttle_scope(self) -> str | None:  # type: ignore[override]
        return "institution_join" if self.request.method == "POST" else None

    @extend_schema(responses=s.MembershipSerializer(many=True))
    def get(self, request: Request) -> Response:
        return Response(s.MembershipSerializer(selectors.user_memberships(request.user), many=True).data)

    @extend_schema(request=s.MembershipRequestSerializer, responses={201: s.MembershipSerializer})
    def post(self, request: Request) -> Response:
        serializer = s.MembershipRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        institution = selectors.get_institution(data.pop("institution"))
        data = resolve_references(institution, data)
        membership = services.request_membership(user=request.user, institution=institution, **data)
        return Response(s.MembershipSerializer(membership).data, status=status.HTTP_201_CREATED)


class MyMembershipDetailView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def _get(self, request: Request, membership_id: Any) -> InstitutionMembership:
        membership = selectors.user_memberships(request.user).filter(pk=membership_id).first()
        if membership is None:
            raise NotFound("Membership not found.")
        return membership

    @extend_schema(responses=s.MembershipSerializer)
    def get(self, request: Request, membership_id: Any) -> Response:
        return Response(s.MembershipSerializer(self._get(request, membership_id)).data)

    @extend_schema(request=s.MembershipUpdateSerializer, responses=s.MembershipSerializer)
    def patch(self, request: Request, membership_id: Any) -> Response:
        membership = self._get(request, membership_id)
        serializer = s.MembershipUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        data = resolve_references(membership.institution, dict(serializer.validated_data))
        membership = services.update_membership_details(user=request.user, membership_id=membership.pk, data=data)
        return Response(s.MembershipSerializer(membership).data)

    @extend_schema(responses={204: None})
    def delete(self, request: Request, membership_id: Any) -> Response:
        services.leave_membership(user=request.user, membership_id=membership_id)
        return Response(status=status.HTTP_204_NO_CONTENT)


class MyMembershipPrimaryView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(request=None, responses=s.MembershipSerializer)
    def post(self, request: Request, membership_id: Any) -> Response:
        services.set_primary_membership(user=request.user, membership_id=membership_id)
        membership = selectors.user_memberships(request.user).get(pk=membership_id)
        return Response(s.MembershipSerializer(membership).data)


class MyVerificationView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [JSONParser, MultiPartParser, FormParser]
    throttle_scope = "institution_verification"

    @extend_schema(responses=s.VerificationSerializer(many=True))
    def get(self, request: Request, membership_id: Any) -> Response:
        membership = selectors.user_memberships(request.user).filter(pk=membership_id).first()
        if membership is None:
            raise NotFound("Membership not found.")
        return Response(s.VerificationSerializer(selectors.verification_requests(membership), many=True).data)

    @extend_schema(request=s.VerificationStartSerializer, responses={201: s.VerificationSerializer})
    def post(self, request: Request, membership_id: Any) -> Response:
        serializer = s.VerificationStartSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        method = data.pop("method")
        document = data.pop("document", None)
        verification = services.start_verification(
            user=request.user, membership_id=membership_id, method=method, data=data, file=document
        )
        return Response(s.VerificationSerializer(verification).data, status=status.HTTP_201_CREATED)


class MyVerificationCompleteView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    throttle_scope = "otp_verify"

    @extend_schema(request=s.VerificationCompleteSerializer, responses=s.VerificationSerializer)
    def post(self, request: Request, membership_id: Any, verification_id: Any) -> Response:
        serializer = s.VerificationCompleteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        verification = services.complete_verification(
            user=request.user, verification_id=verification_id, data=serializer.validated_data
        )
        if str(verification.membership_id) != str(membership_id):
            raise NotFound()
        return Response(s.VerificationSerializer(verification).data)


# ---------------------------------------------------------- administration
class MemberListView(InstitutionMixin, generics.ListAPIView):
    """Members of an institution (requires ``institution.memberships.view``)."""

    serializer_class = s.MemberSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = PageNumberPagination

    @extend_schema(parameters=[OpenApiParameter("status", str), OpenApiParameter("role", str)])
    def get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().get(request, *args, **kwargs)

    def get_queryset(self) -> Any:
        institution = self.get_institution()
        authorize(self.request.user, "institution.memberships.view", institution_scope(institution))
        return selectors.institution_memberships(institution, self.request.query_params).prefetch_related(
            "verification_requests"
        )


class MemberActionView(InstitutionMixin, APIView):
    permission_classes = [permissions.IsAuthenticated]
    action: str = "approve"

    @extend_schema(request=s.ReviewSerializer, responses=s.MemberSerializer)
    def post(self, request: Request, institution_id: Any, membership_id: Any) -> Response:
        institution = self.get_institution()
        serializer_class = s.ReviewSerializer if self.action in ("approve",) else s.RequiredReasonSerializer
        serializer = serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        reason = serializer.validated_data.get("reason", "")
        kwargs = {"actor": request.user, "institution": institution, "membership_id": membership_id}
        if self.action == "approve":
            membership = services.review_membership(approve=True, reason=reason, **kwargs)
        elif self.action == "reject":
            membership = services.review_membership(approve=False, reason=reason, **kwargs)
        elif self.action == "suspend":
            membership = services.suspend_membership(reason=reason, **kwargs)
        else:
            membership = services.revoke_membership(reason=reason, **kwargs)
        return Response(s.MemberSerializer(membership).data)


def member_action(action: str) -> type[MemberActionView]:
    return type(f"Member{action.title()}View", (MemberActionView,), {"action": action})


class VerificationDocumentView(InstitutionMixin, APIView):
    """Stream a verification document to an authorised reviewer (audited)."""

    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(responses={(200, "application/octet-stream"): bytes})
    def get(self, request: Request, institution_id: Any, membership_id: Any, verification_id: Any) -> Any:
        institution = self.get_institution()
        authorize(request.user, "institution.memberships.verify", institution_scope(institution), audit_denial=True)
        verification = VerificationRequest.objects.filter(
            pk=verification_id, membership_id=membership_id, membership__institution=institution
        ).first()
        if verification is None or not verification.document:
            raise NotFound()
        audit(
            "institution.verification.document_viewed",
            actor=request.user,
            target=verification,
            scope=("institution", institution.pk),
        )
        response = FileResponse(verification.document.open("rb"), as_attachment=True)
        response["X-Content-Type-Options"] = "nosniff"
        response["Cache-Control"] = "no-store"
        return response


# ------------------------------------------------------------------ announcements
class AnnouncementListCreateView(InstitutionMixin, APIView):
    permission_classes = [permissions.AllowAny]

    @extend_schema(
        parameters=[OpenApiParameter("status", str, description="Managers only: draft, archived or all.")],
        responses=paginated(s.InstitutionAnnouncementSerializer),
    )
    def get(self, request: Request, institution_id: Any) -> Response:
        institution = self.get_institution()
        wanted = request.query_params.get("status")
        if (
            wanted
            and request.user.is_authenticated
            and selectors.can_manage(request.user, institution, announcements.PUBLISH)
        ):
            qs = Announcement.objects.filter(institution=institution).select_related("institution")
            if wanted != "all":
                qs = qs.filter(status=wanted)
        else:
            qs = selectors.visible_announcements(request.user, institution)
        paginator = PageNumberPagination()
        page = paginator.paginate_queryset(qs, request, view=self)
        return paginator.get_paginated_response(s.InstitutionAnnouncementSerializer(page, many=True).data)

    @extend_schema(
        request=s.InstitutionAnnouncementWriteSerializer, responses={201: s.InstitutionAnnouncementSerializer}
    )
    def post(self, request: Request, institution_id: Any) -> Response:
        if not request.user.is_authenticated:
            raise NotFound()
        institution = self.get_institution()
        serializer = s.InstitutionAnnouncementWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        publish_now = data.pop("publish", False)
        announcement = announcements.create_announcement(
            actor=request.user,
            institution=institution,
            data=resolve_references(institution, data),
            publish_now=publish_now,
        )
        return Response(s.InstitutionAnnouncementSerializer(announcement).data, status=status.HTTP_201_CREATED)


class AnnouncementDetailView(InstitutionMixin, APIView):
    permission_classes = [permissions.AllowAny]

    def _get(self, request: Request, announcement_id: Any) -> Announcement:
        announcement = (
            Announcement.objects.filter(pk=announcement_id, institution=self.get_institution())
            .select_related("institution")
            .first()
        )
        if announcement is None or not selectors.can_view_announcement(request.user, announcement):
            raise NotFound()
        return announcement

    @extend_schema(responses=s.InstitutionAnnouncementSerializer)
    def get(self, request: Request, institution_id: Any, announcement_id: Any) -> Response:
        return Response(s.InstitutionAnnouncementSerializer(self._get(request, announcement_id)).data)

    @extend_schema(request=s.InstitutionAnnouncementWriteSerializer, responses=s.InstitutionAnnouncementSerializer)
    def patch(self, request: Request, institution_id: Any, announcement_id: Any) -> Response:
        if not request.user.is_authenticated:
            raise NotFound()
        announcement = self._get(request, announcement_id)
        serializer = s.InstitutionAnnouncementWriteSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        data.pop("publish", None)
        updated = announcements.update_announcement(
            actor=request.user, announcement=announcement, data=resolve_references(announcement.institution, data)
        )
        return Response(s.InstitutionAnnouncementSerializer(updated).data)

    @extend_schema(responses={204: None})
    def delete(self, request: Request, institution_id: Any, announcement_id: Any) -> Response:
        if not request.user.is_authenticated:
            raise NotFound()
        announcements.delete_announcement(actor=request.user, announcement=self._get(request, announcement_id))
        return Response(status=status.HTTP_204_NO_CONTENT)


class _AnnouncementActionView(InstitutionMixin, APIView):
    permission_classes = [permissions.IsAuthenticated]
    operation: Any = None

    @extend_schema(request=None, responses=s.InstitutionAnnouncementSerializer)
    def post(self, request: Request, institution_id: Any, announcement_id: Any) -> Response:
        announcement = Announcement.objects.filter(pk=announcement_id, institution=self.get_institution()).first()
        if announcement is None:
            raise NotFound()
        updated = type(self).operation(actor=request.user, announcement=announcement)
        return Response(s.InstitutionAnnouncementSerializer(updated).data)


class AnnouncementPublishView(_AnnouncementActionView):
    operation = staticmethod(announcements.publish_announcement)


class AnnouncementArchiveView(_AnnouncementActionView):
    operation = staticmethod(announcements.archive_announcement)


class MyAnnouncementsView(APIView):
    """Announcements from every institution where you're a verified member."""

    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(responses=paginated(s.InstitutionAnnouncementSerializer))
    def get(self, request: Request) -> Response:
        paginator = PageNumberPagination()
        page = paginator.paginate_queryset(selectors.my_announcements(request.user), request, view=self)
        return paginator.get_paginated_response(s.InstitutionAnnouncementSerializer(page, many=True).data)
