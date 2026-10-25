from __future__ import annotations

from django.urls import path

from university.permissions.api.v1 import views

app_name = "permissions"

urlpatterns = [
    path("permissions/", views.PermissionListView.as_view(), name="permission-list"),
    path("roles/", views.RoleListCreateView.as_view(), name="role-list"),
    path("roles/<uuid:id>/", views.RoleDetailView.as_view(), name="role-detail"),
    path("role-assignments/", views.RoleAssignmentListCreateView.as_view(), name="assignment-list"),
    path("role-assignments/<uuid:assignment_id>/", views.RoleAssignmentDetailView.as_view(), name="assignment-detail"),
    path("me/permissions/", views.MyPermissionsView.as_view(), name="my-permissions"),
]
