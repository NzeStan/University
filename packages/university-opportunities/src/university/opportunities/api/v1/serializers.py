from __future__ import annotations

from typing import Any

from rest_framework import serializers

from university.core.api.schema import extend_schema_field
from university.core.api.serializers import StrictModelSerializer
from university.opportunities.constants import (
    ApplicationStatus,
    ApplyMethod,
    OpportunityAudience,
    OpportunityKind,
    PayPeriod,
    WorkMode,
)
from university.opportunities.models import Application, Opportunity
from university.users.refs import PersonRefSerializer, person_ref


class OpportunityViewerSerializer(serializers.Serializer):
    is_poster = serializers.BooleanField()
    saved = serializers.BooleanField()
    application_status = serializers.CharField(allow_null=True)


class OpportunitySerializer(StrictModelSerializer):
    poster = serializers.SerializerMethodField()
    verified = serializers.SerializerMethodField()
    viewer = serializers.SerializerMethodField()

    class Meta:
        model = Opportunity
        fields = (
            "id", "kind", "title", "organization_name", "organization_url", "description", "location", "work_mode",
            "pay_min_minor", "pay_max_minor", "currency", "pay_period", "deadline", "starts_on", "apply_method",
            "apply_url", "apply_email", "audience", "scope_id", "tags", "status", "verified", "poster",
            "applications_count", "published_at", "closed_at", "created_at", "viewer",
        )  # fmt: skip
        read_only_fields = fields

    @extend_schema_field(PersonRefSerializer)
    def get_poster(self, obj: Opportunity) -> dict[str, Any] | None:
        return person_ref(obj.poster)

    def get_verified(self, obj: Opportunity) -> bool:
        return obj.verified_at is not None

    @extend_schema_field(OpportunityViewerSerializer)
    def get_viewer(self, obj: Opportunity) -> dict[str, Any]:
        viewer = self.context.get("viewer")
        authenticated = bool(viewer is not None and getattr(viewer, "is_authenticated", False))
        saved = self.context.get("saved", set())
        applied = self.context.get("applied", {})
        return {
            "is_poster": authenticated and viewer.pk == obj.poster_id,
            "saved": obj.pk in saved,
            "application_status": applied.get(obj.pk),
        }


class OpportunityWriteSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=OpportunityKind.choices)
    title = serializers.CharField(max_length=200)
    organization_name = serializers.CharField(max_length=200)
    organization_url = serializers.URLField(required=False, allow_blank=True)
    description = serializers.CharField(max_length=20000)
    location = serializers.CharField(max_length=120, required=False, allow_blank=True)
    work_mode = serializers.ChoiceField(choices=WorkMode.choices, default=WorkMode.ON_SITE)
    pay_min_minor = serializers.IntegerField(min_value=0, required=False, allow_null=True)
    pay_max_minor = serializers.IntegerField(min_value=0, required=False, allow_null=True)
    currency = serializers.CharField(max_length=3, default="NGN")
    pay_period = serializers.ChoiceField(choices=PayPeriod.choices, default=PayPeriod.MONTH)
    deadline = serializers.DateTimeField(required=False, allow_null=True)
    starts_on = serializers.DateField(required=False, allow_null=True)
    apply_method = serializers.ChoiceField(choices=ApplyMethod.choices, default=ApplyMethod.IN_APP)
    apply_url = serializers.URLField(required=False, allow_blank=True)
    apply_email = serializers.EmailField(required=False, allow_blank=True)
    audience = serializers.ChoiceField(choices=OpportunityAudience.choices, default=OpportunityAudience.PUBLIC)
    scope_id = serializers.CharField(max_length=64, required=False, allow_blank=True)
    tags = serializers.ListField(child=serializers.CharField(max_length=40), required=False, max_length=10)
    publish = serializers.BooleanField(default=False, write_only=True, help_text="Publish immediately (create only).")


class OpportunityStatusActionSerializer(serializers.Serializer):
    action = serializers.ChoiceField(choices=["publish", "close", "reopen"])


class OpportunityVerifySerializer(serializers.Serializer):
    verified = serializers.BooleanField()


class OpportunityApplySerializer(serializers.Serializer):
    cover_note = serializers.CharField(max_length=4000, required=False, allow_blank=True)
    contact_email = serializers.EmailField(required=False, allow_blank=True)
    resume = serializers.FileField(required=False, help_text="PDF, up to 5 MB. Only the poster can open it.")


class OpportunitySummarySerializer(serializers.Serializer):
    id = serializers.UUIDField()
    title = serializers.CharField()
    organization_name = serializers.CharField()
    status = serializers.CharField()


class OpportunityApplicationSerializer(StrictModelSerializer):
    applicant = serializers.SerializerMethodField()
    opportunity = serializers.SerializerMethodField()
    has_resume = serializers.SerializerMethodField()

    class Meta:
        model = Application
        fields = (
            "id",
            "opportunity",
            "applicant",
            "cover_note",
            "contact_email",
            "has_resume",
            "status",
            "decided_at",
            "created_at",
        )
        read_only_fields = fields

    @extend_schema_field(PersonRefSerializer)
    def get_applicant(self, obj: Application) -> dict[str, Any] | None:
        return person_ref(obj.applicant)

    @extend_schema_field(OpportunitySummarySerializer)
    def get_opportunity(self, obj: Application) -> dict[str, Any]:
        o = obj.opportunity
        return {"id": str(o.pk), "title": o.title, "organization_name": o.organization_name, "status": o.status}

    def get_has_resume(self, obj: Application) -> bool:
        return bool(obj.resume)


class OpportunityDecisionSerializer(serializers.Serializer):
    status = serializers.ChoiceField(
        choices=[ApplicationStatus.SHORTLISTED, ApplicationStatus.REJECTED, ApplicationStatus.HIRED]
    )
