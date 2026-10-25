from __future__ import annotations

from django.urls import path

from university.creator.api.v1 import views

app_name = "creator"

ME = "me/creator/"
C = "campaigns/<uuid:campaign_id>/"

urlpatterns = [
    path("creator-categories/", views.CategoryListView.as_view(), name="category-list"),
    path("creator-providers/", views.ProviderListView.as_view(), name="provider-list"),
    # Creators
    path("creators/", views.CreatorListView.as_view(), name="creator-list"),
    path("creators/<uuid:profile_id>/revoke-verification/", views.RevokeVerificationView.as_view(), name="revoke"),
    path("creators/<uuid:profile_id>/analytics/", views.CreatorAnalyticsView.as_view(), name="creator-analytics"),
    path("creators/<str:lookup>/", views.CreatorDetailView.as_view(), name="creator-detail"),
    path("creators/<str:lookup>/media-kit/", views.CreatorMediaKitView.as_view(), name="creator-media-kit"),
    # The authenticated creator
    path(ME, views.MyCreatorProfileView.as_view(), name="my-creator"),
    path(f"{ME}linked-accounts/", views.MyLinkedAccountsView.as_view(), name="my-linked-accounts"),
    path(
        f"{ME}linked-accounts/<uuid:account_id>/", views.MyLinkedAccountDetailView.as_view(), name="my-linked-account"
    ),
    path(
        f"{ME}linked-accounts/<uuid:account_id>/verify/",
        views.MyLinkedAccountVerifyView.as_view(),
        name="my-linked-account-verify",
    ),
    path(f"{ME}verification/", views.MyVerificationView.as_view(), name="my-verification"),
    path(f"{ME}media-kit/", views.MyMediaKitView.as_view(), name="my-media-kit"),
    path(f"{ME}media-kit/rotate-link/", views.MyMediaKitRotateView.as_view(), name="my-media-kit-rotate"),
    path(f"{ME}analytics/", views.MyAnalyticsView.as_view(), name="my-analytics"),
    path(f"{ME}campaigns/", views.MyParticipationsView.as_view(), name="my-participations"),
    path("me/campaigns/", views.MyCampaignsView.as_view(), name="my-campaigns"),
    # Reviewers
    path("creator/verification-requests/", views.VerificationQueueView.as_view(), name="verification-queue"),
    path(
        "creator/verification-requests/<uuid:request_id>/approve/",
        views.VerificationDecisionView.as_view(),
        name="verification-approve",
    ),
    path(
        "creator/verification-requests/<uuid:request_id>/reject/",
        type("RejectVerificationView", (views.VerificationDecisionView,), {"approve": False}).as_view(),
        name="verification-reject",
    ),
    path("creator/linked-accounts/", views.AccountReviewQueueView.as_view(), name="account-review-queue"),
    path(
        "creator/linked-accounts/<uuid:account_id>/confirm/", views.AccountConfirmView.as_view(), name="account-confirm"
    ),
    # Campaigns
    path("campaigns/", views.CampaignListCreateView.as_view(), name="campaign-list"),
    path(C, views.CampaignDetailView.as_view(), name="campaign-detail"),
    path(f"{C}publish/", views.campaign_action("publish").as_view(), name="campaign-publish"),
    path(f"{C}close/", views.campaign_action("close").as_view(), name="campaign-close"),
    path(f"{C}complete/", views.campaign_action("complete").as_view(), name="campaign-complete"),
    path(f"{C}cancel/", views.campaign_action("cancel").as_view(), name="campaign-cancel"),
    path(f"{C}participations/", views.CampaignParticipationsView.as_view(), name="campaign-participations"),
    path(f"{C}apply/", views.CampaignApplyView.as_view(), name="campaign-apply"),
    path(f"{C}invitations/", views.CampaignInviteView.as_view(), name="campaign-invite"),
    path(
        "participations/<uuid:participation_id>/decision/",
        views.ParticipationDecisionView.as_view(),
        name="participation-decision",
    ),
    path(
        "participations/<uuid:participation_id>/deliverables/",
        views.DeliverableListView.as_view(),
        name="deliverable-list",
    ),
    path(
        "deliverables/<uuid:deliverable_id>/submit/", views.DeliverableSubmitView.as_view(), name="deliverable-submit"
    ),
    path(
        "deliverables/<uuid:deliverable_id>/review/", views.DeliverableReviewView.as_view(), name="deliverable-review"
    ),
]
