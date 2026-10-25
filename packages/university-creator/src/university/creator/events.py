"""Event-bus names published by the creator module (payloads carry ids only)."""

PROFILE_CREATED = "creator.profile.created"
PROFILE_UPDATED = "creator.profile.updated"
VERIFICATION_REQUESTED = "creator.verification.requested"
VERIFICATION_APPROVED = "creator.verification.approved"
VERIFICATION_REJECTED = "creator.verification.rejected"
VERIFICATION_REVOKED = "creator.verification.revoked"
ACCOUNT_VERIFIED = "creator.account.verified"

CAMPAIGN_PUBLISHED = "creator.campaign.published"
CAMPAIGN_CLOSED = "creator.campaign.closed"
CAMPAIGN_COMPLETED = "creator.campaign.completed"
CAMPAIGN_CANCELLED = "creator.campaign.cancelled"
CAMPAIGN_HIDDEN = "creator.campaign.hidden"

#: ``status`` is the new participation status; payloads carry creator_user_id and owner_id.
PARTICIPATION_CHANGED = "creator.participation.changed"
DELIVERABLE_SUBMITTED = "creator.deliverable.submitted"
DELIVERABLE_REVIEWED = "creator.deliverable.reviewed"
