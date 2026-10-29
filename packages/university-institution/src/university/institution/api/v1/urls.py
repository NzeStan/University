from __future__ import annotations

from django.urls import path

from university.institution.api.v1 import serializers as s
from university.institution.api.v1 import views

app_name = "institution"

base = "institutions/<uuid:institution_id>/"

urlpatterns = [
    path("institution-types/", views.InstitutionTypeListView.as_view(), name="type-list"),
    path("institutions/", views.InstitutionListCreateView.as_view(), name="institution-list"),
    path(base, views.InstitutionDetailView.as_view(), name="institution-detail"),
    path(f"{base}domains/", views.DomainListCreateView.as_view(), name="domain-list"),
    path(f"{base}domains/<uuid:domain_id>/", views.DomainDetailView.as_view(), name="domain-detail"),
    # Academic structure
    path(f"{base}campuses/", views.structure_view("campus", s.CampusSerializer).as_view(), name="campus-list"),
    path(f"{base}units/", views.structure_view("unit", s.AcademicUnitSerializer).as_view(), name="unit-list"),
    path(
        f"{base}programmes/",
        views.structure_view("programme", s.ProgrammeSerializer).as_view(),
        name="programme-list",
    ),
    path(f"{base}levels/", views.structure_view("level", s.LevelSerializer).as_view(), name="level-list"),
    path(
        f"{base}sessions/",
        views.structure_view("session", s.AcademicSessionSerializer).as_view(),
        name="session-list",
    ),
    path(f"{base}sessions/<uuid:session_id>/semesters/", views.SemesterCreateView.as_view(), name="semester-create"),
    path(f"{base}announcements/", views.AnnouncementListCreateView.as_view(), name="announcement-list"),
    path(
        f"{base}announcements/<uuid:announcement_id>/",
        views.AnnouncementDetailView.as_view(),
        name="announcement-detail",
    ),
    path(
        f"{base}announcements/<uuid:announcement_id>/publish/",
        views.AnnouncementPublishView.as_view(),
        name="announcement-publish",
    ),
    path(
        f"{base}announcements/<uuid:announcement_id>/archive/",
        views.AnnouncementArchiveView.as_view(),
        name="announcement-archive",
    ),
    path(
        f"{base}<str:kind>/<uuid:object_id>/",
        views.StructureDetailView.as_view(),
        name="structure-detail",
    ),
    # Membership administration
    path(f"{base}memberships/", views.MemberListView.as_view(), name="member-list"),
    path(
        f"{base}memberships/<uuid:membership_id>/approve/",
        views.member_action("approve").as_view(),
        name="member-approve",
    ),
    path(
        f"{base}memberships/<uuid:membership_id>/reject/",
        views.member_action("reject").as_view(),
        name="member-reject",
    ),
    path(
        f"{base}memberships/<uuid:membership_id>/suspend/",
        views.member_action("suspend").as_view(),
        name="member-suspend",
    ),
    path(
        f"{base}memberships/<uuid:membership_id>/revoke/",
        views.member_action("revoke").as_view(),
        name="member-revoke",
    ),
    path(
        f"{base}memberships/<uuid:membership_id>/verifications/<uuid:verification_id>/document/",
        views.VerificationDocumentView.as_view(),
        name="verification-document",
    ),
    # The authenticated user's memberships
    path("me/memberships/", views.MyMembershipListCreateView.as_view(), name="my-membership-list"),
    path("me/memberships/<uuid:membership_id>/", views.MyMembershipDetailView.as_view(), name="my-membership-detail"),
    path(
        "me/memberships/<uuid:membership_id>/primary/",
        views.MyMembershipPrimaryView.as_view(),
        name="my-membership-primary",
    ),
    path(
        "me/memberships/<uuid:membership_id>/verifications/",
        views.MyVerificationView.as_view(),
        name="my-verification",
    ),
    path(
        "me/memberships/<uuid:membership_id>/verifications/<uuid:verification_id>/complete/",
        views.MyVerificationCompleteView.as_view(),
        name="my-verification-complete",
    ),
    path("me/announcements/", views.MyAnnouncementsView.as_view(), name="my-announcements"),
]
