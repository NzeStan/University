"""Institution API serializers.

Related objects are accepted as UUIDs and resolved *within the institution*
by the services — a client can never attach another institution's campus or
programme to a membership.
"""

from __future__ import annotations

from typing import Any

from rest_framework import serializers

from university.core.api.schema import extend_schema_field
from university.core.api.serializers import StrictModelSerializer
from university.institution.constants import ANNOUNCEMENT_CATEGORIES, AnnouncementAudience, AnnouncementPriority
from university.institution.models import (
    AcademicSession,
    AcademicUnit,
    Announcement,
    Campus,
    Institution,
    InstitutionDomain,
    InstitutionMembership,
    InstitutionType,
    Level,
    Programme,
    Semester,
    VerificationRequest,
)
from university.users.refs import PersonRefSerializer, person_ref


class InstitutionTypeSerializer(StrictModelSerializer):
    class Meta:
        model = InstitutionType
        fields = ("id", "key", "name", "description")
        read_only_fields = fields


class InstitutionSummarySerializer(StrictModelSerializer):
    type = serializers.SlugRelatedField(slug_field="key", read_only=True)

    class Meta:
        model = Institution
        fields = ("id", "name", "short_name", "slug", "type", "country", "region", "city", "is_verified")
        read_only_fields = fields


class InstitutionSerializer(StrictModelSerializer):
    type = serializers.SlugRelatedField(slug_field="key", queryset=InstitutionType.objects.filter(is_active=True))
    verification_methods = serializers.ListField(child=serializers.CharField(max_length=32), required=False)
    available_verification_methods = serializers.SerializerMethodField()
    country = serializers.RegexField(r"^[A-Za-z]{2}$", help_text="ISO 3166-1 alpha-2 code, e.g. NG.")

    class Meta:
        model = Institution
        fields = (
            "id",
            "name",
            "short_name",
            "slug",
            "type",
            "ownership",
            "country",
            "region",
            "city",
            "website",
            "description",
            "founded_year",
            "status",
            "is_verified",
            "verification_methods",
            "available_verification_methods",
            "created_at",
        )
        read_only_fields = ("id", "available_verification_methods", "created_at")
        extra_kwargs = {"slug": {"required": False, "validators": []}}

    def validate_country(self, value: str) -> str:
        return value.upper()

    def get_available_verification_methods(self, obj: Institution) -> list[str]:
        from university.institution.services.memberships import allowed_methods

        return allowed_methods(obj)


class DomainSerializer(StrictModelSerializer):
    class Meta:
        model = InstitutionDomain
        fields = ("id", "domain", "allow_subdomains", "is_verified")
        read_only_fields = ("id", "is_verified")
        extra_kwargs = {"domain": {"validators": []}}


class CampusSerializer(StrictModelSerializer):
    class Meta:
        model = Campus
        fields = ("id", "name", "slug", "address", "city", "region", "is_main", "is_active")
        read_only_fields = ("id",)
        extra_kwargs = {"slug": {"required": False}}


class AcademicUnitSerializer(StrictModelSerializer):
    parent = serializers.UUIDField(source="parent_id", required=False, allow_null=True)
    campus = serializers.UUIDField(source="campus_id", required=False, allow_null=True)

    class Meta:
        model = AcademicUnit
        fields = ("id", "unit_type", "name", "short_name", "code", "slug", "parent", "campus", "is_active")
        read_only_fields = ("id",)
        extra_kwargs = {"slug": {"required": False}}


class ProgrammeSerializer(StrictModelSerializer):
    academic_unit = serializers.UUIDField(source="academic_unit_id", required=False, allow_null=True)

    class Meta:
        model = Programme
        fields = (
            "id",
            "name",
            "code",
            "award",
            "qualification_level",
            "study_mode",
            "duration_years",
            "academic_unit",
            "is_active",
        )
        read_only_fields = ("id",)


class LevelSerializer(StrictModelSerializer):
    programme = serializers.UUIDField(source="programme_id", required=False, allow_null=True)

    class Meta:
        model = Level
        fields = ("id", "code", "name", "order", "programme")
        read_only_fields = ("id",)


class SemesterSerializer(StrictModelSerializer):
    class Meta:
        model = Semester
        fields = ("id", "name", "order", "starts_on", "ends_on", "is_current")
        read_only_fields = ("id", "is_current")


class AcademicSessionSerializer(StrictModelSerializer):
    semesters = SemesterSerializer(many=True, read_only=True)
    make_current = serializers.BooleanField(write_only=True, required=False, default=False)

    class Meta:
        model = AcademicSession
        fields = ("id", "name", "starts_on", "ends_on", "is_current", "semesters", "make_current")
        read_only_fields = ("id", "is_current", "semesters")


class MembershipSerializer(StrictModelSerializer):
    """A user's own membership."""

    institution = InstitutionSummarySerializer(read_only=True)
    campus = serializers.UUIDField(source="campus_id", read_only=True, allow_null=True)
    academic_unit = serializers.UUIDField(source="academic_unit_id", read_only=True, allow_null=True)
    programme = serializers.UUIDField(source="programme_id", read_only=True, allow_null=True)
    level = serializers.UUIDField(source="level_id", read_only=True, allow_null=True)

    class Meta:
        model = InstitutionMembership
        fields = (
            "id",
            "institution",
            "role",
            "status",
            "campus",
            "academic_unit",
            "programme",
            "level",
            "identifier_hint",
            "entry_year",
            "graduation_year",
            "is_primary",
            "verified_at",
            "verification_method",
            "status_reason",
            "created_at",
        )
        read_only_fields = fields


class MembershipRequestSerializer(serializers.Serializer):
    institution = serializers.UUIDField()
    role = serializers.CharField(max_length=32)
    campus = serializers.UUIDField(required=False, allow_null=True)
    academic_unit = serializers.UUIDField(required=False, allow_null=True)
    programme = serializers.UUIDField(required=False, allow_null=True)
    level = serializers.UUIDField(required=False, allow_null=True)
    entry_year = serializers.IntegerField(required=False, allow_null=True, min_value=1800, max_value=2200)
    graduation_year = serializers.IntegerField(required=False, allow_null=True, min_value=1800, max_value=2200)


class MembershipUpdateSerializer(serializers.Serializer):
    campus = serializers.UUIDField(required=False, allow_null=True)
    academic_unit = serializers.UUIDField(required=False, allow_null=True)
    programme = serializers.UUIDField(required=False, allow_null=True)
    level = serializers.UUIDField(required=False, allow_null=True)
    entry_year = serializers.IntegerField(required=False, allow_null=True, min_value=1800, max_value=2200)
    graduation_year = serializers.IntegerField(required=False, allow_null=True, min_value=1800, max_value=2200)


class VerificationStartSerializer(serializers.Serializer):
    method = serializers.CharField(max_length=32)
    email = serializers.EmailField(required=False)
    identifier = serializers.CharField(max_length=64, required=False)
    note = serializers.CharField(max_length=500, required=False, allow_blank=True)
    document = serializers.FileField(required=False)


class VerificationCompleteSerializer(serializers.Serializer):
    code = serializers.CharField(max_length=12)


class VerificationSerializer(StrictModelSerializer):
    has_document = serializers.SerializerMethodField()

    class Meta:
        model = VerificationRequest
        fields = ("id", "method", "status", "evidence", "has_document", "expires_at", "decided_at", "decision_reason")
        read_only_fields = fields

    def get_has_document(self, obj: VerificationRequest) -> bool:
        return bool(obj.document)


class MemberSerializer(StrictModelSerializer):
    """A membership as seen by institution reviewers — no contact details."""

    user = serializers.SerializerMethodField()
    campus = serializers.UUIDField(source="campus_id", read_only=True, allow_null=True)
    academic_unit = serializers.UUIDField(source="academic_unit_id", read_only=True, allow_null=True)
    programme = serializers.UUIDField(source="programme_id", read_only=True, allow_null=True)
    level = serializers.UUIDField(source="level_id", read_only=True, allow_null=True)
    pending_verification = serializers.SerializerMethodField()

    class Meta:
        model = InstitutionMembership
        fields = (
            "id",
            "user",
            "role",
            "status",
            "campus",
            "academic_unit",
            "programme",
            "level",
            "identifier_hint",
            "entry_year",
            "graduation_year",
            "verified_at",
            "verification_method",
            "pending_verification",
            "created_at",
        )
        read_only_fields = fields

    @extend_schema_field(PersonRefSerializer)
    def get_user(self, obj: InstitutionMembership) -> dict[str, Any] | None:
        return person_ref(obj.user)

    def get_pending_verification(self, obj: InstitutionMembership) -> dict[str, Any] | None:
        from university.institution.constants import OPEN_VERIFICATION_STATUSES

        request = next((r for r in obj.verification_requests.all() if r.status in OPEN_VERIFICATION_STATUSES), None)
        return VerificationSerializer(request).data if request else None


class ReviewSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")


class RequiredReasonSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=255)


# ------------------------------------------------------------------ announcements
class InstitutionAnnouncerSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()
    slug = serializers.CharField()
    is_verified = serializers.BooleanField()


class InstitutionAnnouncementSerializer(StrictModelSerializer):
    """An official announcement. ``verified`` is true when the institution itself is verified."""

    institution = serializers.SerializerMethodField()
    campus = serializers.UUIDField(source="campus_id", read_only=True, allow_null=True)
    academic_unit = serializers.UUIDField(source="academic_unit_id", read_only=True, allow_null=True)
    verified = serializers.SerializerMethodField()

    class Meta:
        model = Announcement
        fields = (
            "id",
            "institution",
            "title",
            "body",
            "category",
            "audience",
            "campus",
            "academic_unit",
            "priority",
            "pinned",
            "status",
            "verified",
            "published_at",
            "expires_at",
            "created_at",
        )
        read_only_fields = fields

    @extend_schema_field(InstitutionAnnouncerSerializer)
    def get_institution(self, obj: Announcement) -> dict[str, Any]:
        i = obj.institution
        return {"id": str(i.pk), "name": i.name, "slug": i.slug, "is_verified": i.is_verified}

    def get_verified(self, obj: Announcement) -> bool:
        return bool(obj.institution.is_verified)


class InstitutionAnnouncementWriteSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=200)
    body = serializers.CharField(max_length=10000)
    category = serializers.ChoiceField(choices=ANNOUNCEMENT_CATEGORIES, default="general")
    audience = serializers.ChoiceField(choices=AnnouncementAudience.choices, default=AnnouncementAudience.MEMBERS)
    campus = serializers.UUIDField(required=False, allow_null=True)
    academic_unit = serializers.UUIDField(required=False, allow_null=True)
    priority = serializers.ChoiceField(choices=AnnouncementPriority.choices, default=AnnouncementPriority.NORMAL)
    pinned = serializers.BooleanField(default=False)
    expires_at = serializers.DateTimeField(required=False, allow_null=True)
    publish = serializers.BooleanField(default=False, write_only=True, help_text="Publish immediately (create only).")
