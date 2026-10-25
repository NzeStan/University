from __future__ import annotations

from django.urls import path

from university.audit.api.v1 import views

app_name = "audit"

urlpatterns = [
    path("audit/logs/", views.AuditLogListView.as_view(), name="log-list"),
    path("me/activity/", views.MyActivityView.as_view(), name="my-activity"),
]
