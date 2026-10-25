from __future__ import annotations

from django.urls import path

from university.moderation.api.v1 import views

app_name = "moderation"

urlpatterns = [
    # Everyone
    path("reasons/", views.ReasonListView.as_view(), name="reason-list"),
    path("reports/", views.ReportCreateView.as_view(), name="report-create"),
    path("appeals/", views.AppealCreateView.as_view(), name="appeal-create"),
    path("me/reports/", views.MyReportsView.as_view(), name="my-reports"),
    path("me/actions/", views.MyActionsView.as_view(), name="my-actions"),
    path("me/appeals/", views.MyAppealsView.as_view(), name="my-appeals"),
    # Moderators (authorised per scope in selectors/services)
    path("cases/", views.CaseListView.as_view(), name="case-list"),
    path("cases/<uuid:case_id>/", views.CaseDetailView.as_view(), name="case-detail"),
    path("cases/<uuid:case_id>/assign/", views.CaseAssignView.as_view(), name="case-assign"),
    path("cases/<uuid:case_id>/actions/", views.CaseActionView.as_view(), name="case-action"),
    path("appeal-queue/", views.AppealQueueView.as_view(), name="appeal-queue"),
    path("appeals/<uuid:appeal_id>/decide/", views.AppealDecideView.as_view(), name="appeal-decide"),
    path("restrictions/<uuid:restriction_id>/lift/", views.RestrictionLiftView.as_view(), name="restriction-lift"),
    path("rules/", views.RuleListView.as_view(), name="rule-list"),
    path("rules/<uuid:id>/", views.RuleDetailView.as_view(), name="rule-detail"),
]
