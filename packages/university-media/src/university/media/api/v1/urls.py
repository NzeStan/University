from __future__ import annotations

from django.urls import path

from university.media.api.v1 import views

app_name = "media"

urlpatterns = [
    path("", views.MediaListCreateView.as_view(), name="media-list"),
    path("uploads/", views.DirectUploadStartView.as_view(), name="direct-upload"),
    path("uploads/<uuid:upload_id>/complete/", views.DirectUploadCompleteView.as_view(), name="direct-upload-complete"),
    path("files/<str:token>/", views.MediaFileView.as_view(), name="file"),
    path("<uuid:asset_id>/", views.MediaDetailView.as_view(), name="media-detail"),
    path("<uuid:asset_id>/clips/", views.MediaClipView.as_view(), name="media-clip"),
]
