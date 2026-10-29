from __future__ import annotations

from django.urls import path

from university.opportunities.api.v1 import views

app_name = "opportunities"

urlpatterns = [
    path("", views.OpportunityListCreateView.as_view(), name="opportunity-list"),
    path("me/posted/", views.MyPostedView.as_view(), name="my-posted"),
    path("me/saved/", views.MySavedView.as_view(), name="my-saved"),
    path("me/applications/", views.MyApplicationsView.as_view(), name="my-applications"),
    path("applications/<uuid:application_id>/", views.ApplicationDetailView.as_view(), name="application-detail"),
    path(
        "applications/<uuid:application_id>/withdraw/",
        views.ApplicationWithdrawView.as_view(),
        name="application-withdraw",
    ),
    path(
        "applications/<uuid:application_id>/resume/", views.ApplicationResumeView.as_view(), name="application-resume"
    ),
    path("<uuid:opportunity_id>/", views.OpportunityDetailView.as_view(), name="opportunity-detail"),
    path("<uuid:opportunity_id>/status/", views.OpportunityStatusView.as_view(), name="opportunity-status"),
    path("<uuid:opportunity_id>/verify/", views.OpportunityVerifyView.as_view(), name="opportunity-verify"),
    path("<uuid:opportunity_id>/apply/", views.OpportunityApplyView.as_view(), name="opportunity-apply"),
    path(
        "<uuid:opportunity_id>/applications/",
        views.OpportunityApplicationsView.as_view(),
        name="opportunity-applications",
    ),
    path("<uuid:opportunity_id>/save/", views.SaveView.as_view(), name="opportunity-save"),
]
