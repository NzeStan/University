"""Event-bus names published by the payments module (payloads carry ids only)."""

PAYMENT_SUCCEEDED = "payments.payment.succeeded"
PAYMENT_FAILED = "payments.payment.failed"
#: Paid, but the seller couldn't fulfil (e.g. hold expired): refunded automatically.
PAYMENT_UNFULFILLED = "payments.payment.unfulfilled"
REFUND_SUCCEEDED = "payments.refund.succeeded"
REFUND_FAILED = "payments.refund.failed"
FUNDS_RELEASED = "payments.funds.released"
PAYOUT_REQUESTED = "payments.payout.requested"
PAYOUT_PAID = "payments.payout.paid"
PAYOUT_REJECTED = "payments.payout.rejected"
