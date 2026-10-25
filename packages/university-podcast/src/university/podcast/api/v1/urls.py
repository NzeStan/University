from __future__ import annotations

from django.urls import path

from university.podcast.api.v1 import views

app_name = "podcast"

P = "podcasts/<uuid:podcast_id>/"
E = "podcasts/episodes/<uuid:episode_id>/"

urlpatterns = [
    path("podcasts/", views.PodcastListCreateView.as_view(), name="podcast-list"),
    path("podcasts/by-slug/<slug:slug>/", views.PodcastBySlugView.as_view(), name="podcast-by-slug"),
    path("podcasts/<slug:slug>/feed.xml", views.PodcastFeedView.as_view(), name="feed"),
    path(P, views.PodcastDetailView.as_view(), name="podcast-detail"),
    path(f"{P}status/", views.PodcastStatusView.as_view(), name="podcast-status"),
    path(f"{P}cover/", views.PodcastCoverView.as_view(), name="podcast-cover"),
    path(f"{P}members/", views.PodcastMembersView.as_view(), name="podcast-members"),
    path(f"{P}members/<uuid:user_id>/", views.PodcastMemberDetailView.as_view(), name="podcast-member"),
    path(f"{P}transfer-ownership/", views.PodcastTransferView.as_view(), name="podcast-transfer"),
    path(f"{P}seasons/", views.PodcastSeasonsView.as_view(), name="podcast-seasons"),
    path(f"{P}episodes/", views.PodcastEpisodesView.as_view(), name="podcast-episodes"),
    path(f"{P}subscription/", views.PodcastSubscribeView.as_view(), name="podcast-subscription"),
    path(f"{P}analytics/", views.PodcastAnalyticsView.as_view(), name="podcast-analytics"),
    path(E, views.EpisodeDetailView.as_view(), name="episode-detail"),
    path(f"{E}publish/", views.EpisodePublishView.as_view(), name="episode-publish"),
    path(
        f"{E}unpublish/",
        type("UnpublishEpisodeView", (views.EpisodePublishView,), {"unpublish": True}).as_view(),
        name="episode-unpublish",
    ),
    path(f"{E}stream/", views.EpisodeStreamView.as_view(), name="episode-stream"),
    path(f"{E}plays/", views.EpisodePlayView.as_view(), name="episode-plays"),
    path(f"{E}guests/", views.EpisodeGuestsView.as_view(), name="episode-guests"),
    path(f"{E}guests/<uuid:guest_id>/", views.EpisodeGuestDetailView.as_view(), name="episode-guest"),
    path(f"{E}transcript/", views.EpisodeTranscriptView.as_view(), name="episode-transcript"),
    path(f"{E}transcript.vtt", views.EpisodeTranscriptVttView.as_view(), name="episode-transcript-vtt"),
    path(f"{E}transcript/generate/", views.EpisodeTranscribeView.as_view(), name="episode-transcribe"),
    path(f"{E}clips/", views.EpisodeClipsView.as_view(), name="episode-clips"),
    path("podcasts/clips/<uuid:clip_id>/", views.ClipDetailView.as_view(), name="clip-detail"),
    path("podcasts/clips/<uuid:clip_id>/stream/", views.ClipStreamView.as_view(), name="clip-stream"),
    path("podcasts/guest-spots/<uuid:guest_id>/respond/", views.GuestResponseView.as_view(), name="guest-respond"),
    path("me/podcast-subscriptions/", views.MySubscriptionsView.as_view(), name="my-subscriptions"),
    path("me/podcasts/", views.MyPodcastsView.as_view(), name="my-podcasts"),
]
