from __future__ import annotations

from django.urls import path

from university.core.api.v1 import views

app_name = "core"

urlpatterns = [
    path("meta/modules/", views.ModulesView.as_view(), name="modules"),
]
