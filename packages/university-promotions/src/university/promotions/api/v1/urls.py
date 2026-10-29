from __future__ import annotations

from django.urls import path

from university.promotions.api.v1 import views

app_name = "promotions"

urlpatterns = [
    path("options/", views.OptionsView.as_view(), name="options"),
    path("campaigns/", views.CampaignListCreateView.as_view(), name="campaign-list"),
    path("campaigns/<uuid:campaign_id>/", views.CampaignDetailView.as_view(), name="campaign-detail"),
    path("campaigns/<uuid:campaign_id>/image/", views.CampaignImageView.as_view(), name="campaign-image"),
    path("campaigns/<uuid:campaign_id>/submit/", views.SubmitView.as_view(), name="campaign-submit"),
    path("campaigns/<uuid:campaign_id>/pause/", views.PauseView.as_view(), name="campaign-pause"),
    path("campaigns/<uuid:campaign_id>/resume/", views.ResumeView.as_view(), name="campaign-resume"),
    path("campaigns/<uuid:campaign_id>/stats/", views.StatsView.as_view(), name="campaign-stats"),
    path("campaigns/<uuid:campaign_id>/review/", views.ReviewView.as_view(), name="campaign-review"),
    path("review-queue/", views.ReviewQueueView.as_view(), name="review-queue"),
    path("serve/", views.ServeView.as_view(), name="serve"),
    path("impressions/", views.ImpressionView.as_view(), name="impressions"),
    path("clicks/", views.ClickView.as_view(), name="clicks"),
]
