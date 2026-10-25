from university.core import CORE_APPS
from university.core.api.schema import spectacular_settings
from university.core.testing import build_test_settings

globals().update(
    build_test_settings(
        installed_apps=[
            "drf_spectacular",
            *CORE_APPS,
            "university.institution",
            "university.social",
            "university.moderation",
            "university.anonymous",
            "university.community",
            "university.notifications",
            "university.events",
            "university.creator",
            "university.payments",
            "university.marketplace",
            "university.media",
            "university.podcast",
            "university.analytics",
            "university.trending",
            "university.search",
        ],
        root_urlconf="tests.urls",
        STORAGES={
            "default": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
            "private": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
            "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
        },
    )
)

SPECTACULAR_SETTINGS = spectacular_settings(
    ENUM_NAME_OVERRIDES={
        **spectacular_settings()["ENUM_NAME_OVERRIDES"],
        "MembershipStatusEnum": "university.institution.constants.MembershipStatus",
        "VerificationStatusEnum": "university.institution.constants.VerificationStatus",
        "InstitutionStatusEnum": "university.institution.constants.InstitutionStatus",
        "SocialVisibilityEnum": "university.social.constants.Visibility",
        "ContentStatusEnum": "university.social.constants.ContentStatus",
        "CaseStatusEnum": "university.moderation.constants.CaseStatus",
        "ModerationActionEnum": "university.moderation.constants.Action",
        "AppealStatusEnum": "university.moderation.constants.AppealStatus",
        "SeverityEnum": "university.moderation.constants.Severity",
        "CommunityPrivacyEnum": "university.community.constants.Privacy",
        "CommunityStatusEnum": "university.community.constants.CommunityStatus",
        "CommunityRoleEnum": "university.community.constants.Role",
        "CommunityMembershipStatusEnum": "university.community.constants.MembershipStatus",
        "EventStatusEnum": "university.events.constants.EventStatus",
        "AudienceVisibilityEnum": "university.events.constants.EventVisibility",
        "EventRegistrationStatusEnum": "university.events.constants.RegistrationStatus",
        "CreatorVerificationStatusEnum": "university.creator.constants.VerificationStatus",
        "CreatorRequestStatusEnum": "university.creator.constants.RequestStatus",
        "CreatorProfileStatusEnum": "university.creator.constants.ProfileStatus",
        "CampaignStatusEnum": "university.creator.constants.CampaignStatus",
        "CampaignVisibilityEnum": "university.creator.constants.CampaignVisibility",
        "ParticipationStatusEnum": "university.creator.constants.ParticipationStatus",
        "DeliverableStatusEnum": "university.creator.constants.DeliverableStatus",
        "MediaKitVisibilityEnum": "university.creator.constants.KitVisibility",
        "ListingVisibilityEnum": "university.marketplace.constants.ListingVisibility",
        "DisputeOutcomeEnum": "university.marketplace.constants.DisputeOutcome",
        "MarketOrderStatusEnum": "university.marketplace.constants.OrderStatus",
        "PaymentIntentStatusEnum": "university.payments.constants.IntentStatus",
        "PayoutStatusEnum": "university.payments.constants.PayoutStatus",
        "RefundStatusEnum": "university.payments.constants.RefundStatus",
        "MediaKindEnum": "university.media.models.AssetKind",
        "MediaStatusEnum": "university.media.models.AssetStatus",
        "TranscriptFormatEnum": "university.podcast.constants.TranscriptFormat",
        "EventFormatEnum": "university.events.constants.EventFormat",
        "PodcastStatusEnum": "university.podcast.constants.ShowStatus",
        "EpisodeStatusEnum": "university.podcast.constants.EpisodeStatus",
    }
)
