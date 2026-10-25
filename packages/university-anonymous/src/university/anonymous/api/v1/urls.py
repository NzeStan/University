from __future__ import annotations

from django.urls import path

from university.anonymous.api.v1 import views

app_name = "anonymous"

urlpatterns = [
    path("posts/", views.FeedView.as_view(), name="post-list"),
    path("posts/<uuid:post_id>/", views.PostDetailView.as_view(), name="post-detail"),
    path("posts/<uuid:post_id>/comments/", views.CommentListCreateView.as_view(), name="post-comments"),
    path("posts/<uuid:post_id>/reaction/", views.ReactionView.as_view(), name="post-reaction"),
    path("posts/<uuid:post_id>/hide/", views.HideView.as_view(), name="post-hide"),
    path("comments/<uuid:comment_id>/", views.CommentDetailView.as_view(), name="comment-detail"),
    path("reveal-requests/", views.RevealRequestListCreateView.as_view(), name="reveal-list"),
    path("reveal-requests/<uuid:request_id>/decide/", views.RevealDecisionView.as_view(), name="reveal-decide"),
    path("reveal-requests/<uuid:request_id>/identity/", views.RevealIdentityView.as_view(), name="reveal-identity"),
]
