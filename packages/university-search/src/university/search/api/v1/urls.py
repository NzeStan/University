from __future__ import annotations

from django.urls import path

from university.search.api.v1 import views

app_name = "search"

urlpatterns = [
    path("", views.SearchView.as_view(), name="search"),
    path("people/", views.PeopleSearchView.as_view(), name="people"),
    path("types/", views.SearchTypesView.as_view(), name="types"),
]
