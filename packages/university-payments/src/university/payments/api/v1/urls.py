from __future__ import annotations

from django.urls import path

from university.payments.api.v1 import views
from university.payments.webhooks import PaymentWebhookView

app_name = "payments"

urlpatterns = [
    path("providers/", views.ProviderListView.as_view(), name="provider-list"),
    path("checkout/", views.CheckoutView.as_view(), name="checkout"),
    path("", views.MyPaymentsView.as_view(), name="my-payments"),
    path("me/balance/", views.MyBalanceView.as_view(), name="my-balance"),
    path("me/payouts/", views.MyPayoutsView.as_view(), name="my-payouts"),
    path("me/payouts/<uuid:payout_id>/cancel/", views.MyPayoutCancelView.as_view(), name="my-payout-cancel"),
    path("payouts/", views.PayoutQueueView.as_view(), name="payout-queue"),
    path("payouts/<uuid:payout_id>/approve/", views.PayoutDecisionView.as_view(), name="payout-approve"),
    path(
        "payouts/<uuid:payout_id>/reject/",
        type("RejectPayoutView", (views.PayoutDecisionView,), {"approve": False}).as_view(),
        name="payout-reject",
    ),
    path("webhooks/<slug:provider>/", PaymentWebhookView.as_view(), name="webhook"),
    path("<str:reference>/", views.PaymentDetailView.as_view(), name="payment-detail"),
    path("<str:reference>/verify/", views.PaymentVerifyView.as_view(), name="payment-verify"),
    path("<str:reference>/refunds/", views.PaymentRefundView.as_view(), name="payment-refunds"),
]
