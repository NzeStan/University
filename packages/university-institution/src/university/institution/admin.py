from __future__ import annotations

from typing import Any

from django.contrib import admin, messages

from university.core.exceptions import UniversityError
from university.institution import services
from university.institution.models import (
    AcademicSession,
    AcademicUnit,
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


@admin.register(InstitutionType)
class InstitutionTypeAdmin(admin.ModelAdmin):
    list_display = ("name", "key", "is_active", "ordering")
    list_editable = ("is_active", "ordering")


class DomainInline(admin.TabularInline):
    model = InstitutionDomain
    extra = 0


class CampusInline(admin.TabularInline):
    model = Campus
    extra = 0
    prepopulated_fields = {"slug": ("name",)}


@admin.register(Institution)
class InstitutionAdmin(admin.ModelAdmin):
    list_display = ("name", "short_name", "type", "country", "region", "status", "is_verified")
    list_filter = ("type", "country", "status", "is_verified")
    search_fields = ("name", "short_name", "slug", "city")
    prepopulated_fields = {"slug": ("short_name",)}
    inlines = (DomainInline, CampusInline)

    def get_queryset(self, request: Any) -> Any:
        return Institution.all_objects.select_related("type")


@admin.register(AcademicUnit)
class AcademicUnitAdmin(admin.ModelAdmin):
    list_display = ("name", "unit_type", "institution", "parent", "is_active")
    list_filter = ("unit_type", "is_active")
    search_fields = ("name", "code", "institution__name")
    raw_id_fields = ("institution", "parent", "campus")


@admin.register(Programme)
class ProgrammeAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "award", "institution", "qualification_level", "is_active")
    list_filter = ("qualification_level", "study_mode", "is_active")
    search_fields = ("name", "code", "institution__name")
    raw_id_fields = ("institution", "academic_unit")


@admin.register(Level)
class LevelAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "institution", "programme", "order")
    raw_id_fields = ("institution", "programme")


class SemesterInline(admin.TabularInline):
    model = Semester
    extra = 0


@admin.register(AcademicSession)
class AcademicSessionAdmin(admin.ModelAdmin):
    list_display = ("name", "institution", "starts_on", "ends_on", "is_current")
    list_filter = ("is_current",)
    raw_id_fields = ("institution",)
    inlines = (SemesterInline,)


class VerificationInline(admin.TabularInline):
    model = VerificationRequest
    extra = 0
    fields = ("method", "status", "evidence", "decided_at", "decided_by", "decision_reason")
    readonly_fields = fields
    can_delete = False


@admin.register(InstitutionMembership)
class InstitutionMembershipAdmin(admin.ModelAdmin):
    """Status changes go through audited, authorised services."""

    list_display = ("user", "institution", "role", "status", "verified_at", "created_at")
    list_filter = ("status", "role")
    search_fields = ("user__email", "user__handle", "institution__name")
    raw_id_fields = ("user", "institution", "campus", "academic_unit", "programme", "level", "verified_by")
    readonly_fields = (
        "status",
        "identifier_hash",
        "identifier_hint",
        "verified_at",
        "verified_by",
        "verification_method",
        "status_changed_at",
    )
    inlines = (VerificationInline,)
    actions = ["approve_selected", "reject_selected"]

    def _review(self, request: Any, queryset: Any, approve: bool) -> None:
        done = 0
        for membership in queryset.select_related("institution"):
            try:
                services.review_membership(
                    actor=request.user,
                    institution=membership.institution,
                    membership_id=membership.pk,
                    approve=approve,
                    reason="Reviewed in admin",
                )
                done += 1
            except UniversityError as exc:
                self.message_user(request, f"{membership}: {exc.message}", messages.ERROR)
        if done:
            self.message_user(request, f"Reviewed {done} membership(s).", messages.SUCCESS)

    @admin.action(description="Approve selected pending memberships")
    def approve_selected(self, request: Any, queryset: Any) -> None:
        self._review(request, queryset, approve=True)

    @admin.action(description="Reject selected pending memberships")
    def reject_selected(self, request: Any, queryset: Any) -> None:
        self._review(request, queryset, approve=False)
