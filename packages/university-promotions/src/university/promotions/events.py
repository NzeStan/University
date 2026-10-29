"""Events published by promotions (ids only)."""

#: {"campaign_id", "advertiser_id"}
CAMPAIGN_SUBMITTED = "promotions.campaign.submitted"
#: {"campaign_id", "advertiser_id", "approved"}
CAMPAIGN_REVIEWED = "promotions.campaign.reviewed"
#: {"campaign_id", "advertiser_id"}: budget spent or schedule ended.
CAMPAIGN_COMPLETED = "promotions.campaign.completed"
