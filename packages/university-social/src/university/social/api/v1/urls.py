from __future__ import annotations

from django.urls import path

from university.social.api.v1 import views

app_name = "social"

P = "posts/<uuid:post_id>/"
U = "users/<uuid:user_id>/"

urlpatterns = [
    # Posts and feeds
    path("posts/", views.PostCreateView.as_view(), name="post-create"),
    path(P, views.PostDetailView.as_view(), name="post-detail"),
    path(f"{P}reaction/", views.PostReactionView.as_view(), name="post-reaction"),
    path(f"{P}repost/", views.RepostView.as_view(), name="post-repost"),
    path(f"{P}bookmark/", views.BookmarkView.as_view(), name="post-bookmark"),
    path(f"{P}poll/vote/", views.PollVoteView.as_view(), name="post-poll-vote"),
    path(f"{P}comments/", views.CommentListCreateView.as_view(), name="post-comments"),
    path("feeds/<slug:name>/", views.FeedView.as_view(), name="feed"),
    path("hashtags/", views.HashtagSearchView.as_view(), name="hashtag-search"),
    path("hashtags/<str:tag>/posts/", views.HashtagPostsView.as_view(), name="hashtag-posts"),
    path("audiences/<slug:scope_type>/<str:scope_id>/posts/", views.AudiencePostsView.as_view(), name="audience-posts"),
    # Comments
    path("comments/<uuid:comment_id>/", views.CommentDetailView.as_view(), name="comment-detail"),
    path("comments/<uuid:comment_id>/reaction/", views.CommentReactionView.as_view(), name="comment-reaction"),
    # Moderation (authorised in services: social.content.moderate at the content's scope)
    path("posts/<uuid:object_id>/hide/", views.moderation_view("post", "hide").as_view(), name="post-hide"),
    path("posts/<uuid:object_id>/restore/", views.moderation_view("post", "restore").as_view(), name="post-restore"),
    path("comments/<uuid:object_id>/hide/", views.moderation_view("comment", "hide").as_view(), name="comment-hide"),
    path(
        "comments/<uuid:object_id>/restore/",
        views.moderation_view("comment", "restore").as_view(),
        name="comment-restore",
    ),
    # Media
    path("media/", views.MediaUploadView.as_view(), name="media-upload"),
    path("media/<uuid:media_id>/", views.MediaDetailView.as_view(), name="media-detail"),
    # Graph
    path(f"{U}posts/", views.UserPostsView.as_view(), name="user-posts"),
    path(f"{U}follow/", views.FollowView.as_view(), name="user-follow"),
    path(f"{U}followers/", views.FollowersView.as_view(), name="user-followers"),
    path(f"{U}following/", views.FollowingView.as_view(), name="user-following"),
    path(f"{U}block/", views.BlockView.as_view(), name="user-block"),
    path(f"{U}mute/", views.MuteView.as_view(), name="user-mute"),
    path(f"{U}restrict/", views.RestrictView.as_view(), name="user-restrict"),
    # The authenticated user
    path("me/profile/", views.MyProfileView.as_view(), name="my-profile"),
    path("me/bookmarks/", views.BookmarksView.as_view(), name="my-bookmarks"),
    path("me/follow-requests/", views.FollowRequestsView.as_view(), name="follow-requests"),
    path(
        "me/follow-requests/<uuid:follow_id>/approve/",
        type("ApproveFollowView", (views.FollowRequestActionView,), {"approve": True}).as_view(),
        name="follow-request-approve",
    ),
    path(
        "me/follow-requests/<uuid:follow_id>/decline/",
        type("DeclineFollowView", (views.FollowRequestActionView,), {"approve": False}).as_view(),
        name="follow-request-decline",
    ),
    path("me/followers/<uuid:user_id>/", views.RemoveFollowerView.as_view(), name="remove-follower"),
    path("me/blocks/", views.MyBlocksView.as_view(), name="my-blocks"),
    path("me/mutes/", views.MyMutesView.as_view(), name="my-mutes"),
    path("me/restrictions/", views.MyRestrictionsView.as_view(), name="my-restrictions"),
]
