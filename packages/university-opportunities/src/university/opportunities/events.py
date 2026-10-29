"""Events published by the opportunities module (ids only)."""

#: {"opportunity_id", "poster_id", "kind"}
OPPORTUNITY_PUBLISHED = "opportunities.opportunity.published"
OPPORTUNITY_UPDATED = "opportunities.opportunity.updated"
OPPORTUNITY_CLOSED = "opportunities.opportunity.closed"
OPPORTUNITY_HIDDEN = "opportunities.opportunity.hidden"
#: {"application_id", "opportunity_id", "applicant_id", "poster_id"}
APPLICATION_SUBMITTED = "opportunities.application.submitted"
#: {"application_id", "opportunity_id", "applicant_id", "status"}
APPLICATION_STATUS_CHANGED = "opportunities.application.status_changed"
