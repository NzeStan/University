from __future__ import annotations

from django.urls import path

from university.analytics.api.v1 import views

app_name = "analytics"

urlpatterns = [
    path("views/", views.RecordViewView.as_view(), name="record-view"),
    path("overview/", views.OverviewView.as_view(), name="overview"),
    path("metrics/", views.MetricListView.as_view(), name="metrics"),
    path("scopes/<slug:scope_type>/<str:scope_id>/", views.ScopeReportView.as_view(), name="scope-report"),
]
