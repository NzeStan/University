"""Event names published by the institution module (payloads contain ids only)."""

INSTITUTION_CREATED = "institution.created"
INSTITUTION_UPDATED = "institution.updated"
MEMBERSHIP_REQUESTED = "institution.membership.requested"
MEMBERSHIP_VERIFIED = "institution.membership.verified"
#: Alias emitted alongside ``membership.verified`` for consumers of "joined".
INSTITUTION_JOINED = "institution.joined"
MEMBERSHIP_REJECTED = "institution.membership.rejected"
MEMBERSHIP_SUSPENDED = "institution.membership.suspended"
MEMBERSHIP_REVOKED = "institution.membership.revoked"
MEMBERSHIP_LEFT = "institution.membership.left"
VERIFICATION_STARTED = "institution.verification.started"
