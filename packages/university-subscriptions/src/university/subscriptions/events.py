"""Events published by subscriptions (ids only)."""

#: {"subscription_id", "user_id", "plan"}: the first period was paid.
SUBSCRIPTION_ACTIVATED = "subscriptions.subscription.activated"
#: {"subscription_id", "user_id", "plan"}: a further period was paid.
SUBSCRIPTION_RENEWED = "subscriptions.subscription.renewed"
#: {"subscription_id", "user_id", "plan"}: the period ends soon and isn't paid yet.
SUBSCRIPTION_RENEWAL_DUE = "subscriptions.subscription.renewal_due"
#: {"subscription_id", "user_id", "plan"}: entitlements ended.
SUBSCRIPTION_EXPIRED = "subscriptions.subscription.expired"
