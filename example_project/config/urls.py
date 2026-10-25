from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    # Health checks, /api/v1/... (every installed module) and OpenAPI docs.
    path("", include("university.core.urls")),
]

handler404 = "university.core.api.views.json_page_not_found"
handler500 = "university.core.api.views.json_server_error"
handler403 = "university.core.api.views.json_permission_denied"
handler400 = "university.core.api.views.json_bad_request"
