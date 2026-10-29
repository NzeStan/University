from __future__ import annotations

from django.urls import path

from university.subscriptions.api.v1 import views

app_name = "subscriptions"

urlpatterns = [
    path("plans/", views.PlanListView.as_view(), name="plan-list"),
    path("me/", views.MySubscriptionView.as_view(), name="me"),
    path("me/cancel/", views.CancelView.as_view(), name="me-cancel"),
]
