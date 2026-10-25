from __future__ import annotations

from django.urls import path

from university.trending.api.v1 import views

app_name = "trending"

urlpatterns = [path("", views.TrendingView.as_view(), name="trending")]
