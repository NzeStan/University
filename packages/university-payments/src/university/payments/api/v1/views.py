from __future__ import annotations

from typing import Any

from rest_framework import permissions, status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from university.core.api.pagination import PageNumberPagination
from university.core.api.schema import OpenApiParameter, extend_schema
from university.core.exceptions import NotFound
from university.core.idempotency import idempotent
from university.payments import services
from university.payments.api.v1 import serializers as s
from university.payments.ledger import payee_balances
from university.payments.models import PaymentIntent, Payout
from university.payments.providers import providers
from university.permissions.services import authorize, has_permission


def _paginate(view: APIView, request: Request, qs: Any, serializer: Any) -> Response:
    paginator = PageNumberPagination()
    page = paginator.paginate_queryset(qs, request, view=view)
    return paginator.get_paginated_response(serializer(page, many=True).data)


def _visible_intent(user: Any, reference: str) -> PaymentIntent:
    intent = PaymentIntent.objects.filter(reference=reference).first()
    if intent is None or not (intent.payer_id == user.pk or has_permission(user, "payments.view")):
        raise NotFound("Payment not found.")
    return intent


class ProviderListView(APIView):
    permission_classes = [permissions.AllowAny]

    @extend_schema(responses=s.PaymentProviderSerializer(many=True))
    def get(self, request: Request) -> Response:
        return Response([{"key": key, "label": p.label} for key, p in providers().items()])


class CheckoutView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        request=s.PaymentCheckoutSerializer,
        responses={201: s.PaymentIntentSerializer},
        parameters=[OpenApiParameter("Idempotency-Key", str, location=OpenApiParameter.HEADER, required=True)],
    )
    @idempotent("payments.checkout", required=True)
    def post(self, request: Request) -> Response:
        serializer = s.PaymentCheckoutSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        intent = services.start_checkout(
            payer=request.user,
            purpose=data["purpose"],
            object_id=data["object_id"],
            provider=data.get("provider") or None,
            callback_url=data.get("callback_url") or None,
        )
        return Response(s.PaymentIntentSerializer(intent).data, status=status.HTTP_201_CREATED)


class MyPaymentsView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(responses=s.PaymentIntentSerializer(many=True))
    def get(self, request: Request) -> Response:
        qs = PaymentIntent.objects.filter(payer=request.user).order_by("-created_at")
        return _paginate(self, request, qs, s.PaymentIntentSerializer)


class PaymentDetailView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(responses=s.PaymentIntentSerializer)
    def get(self, request: Request, reference: str) -> Response:
        return Response(s.PaymentIntentSerializer(_visible_intent(request.user, reference)).data)


class PaymentVerifyView(APIView):
    """Call after the provider redirects back; the answer always comes from the provider."""

    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(request=None, responses=s.PaymentIntentSerializer)
    def post(self, request: Request, reference: str) -> Response:
        _visible_intent(request.user, reference)
        intent = services.verify_payment(reference=reference, user=request.user)
        return Response(s.PaymentIntentSerializer(intent).data)


class PaymentRefundView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(responses=s.PaymentRefundSerializer(many=True))
    def get(self, request: Request, reference: str) -> Response:
        intent = _visible_intent(request.user, reference)
        return Response(s.PaymentRefundSerializer(intent.refunds.order_by("-created_at"), many=True).data)

    @extend_schema(request=s.PaymentRefundCreateSerializer, responses={201: s.PaymentRefundSerializer})
    @idempotent("payments.refund")
    def post(self, request: Request, reference: str) -> Response:
        serializer = s.PaymentRefundCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        refund = services.refund_payment(actor=request.user, reference=reference, **serializer.validated_data)
        return Response(s.PaymentRefundSerializer(refund).data, status=status.HTTP_201_CREATED)


class MyBalanceView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(responses=s.PaymentBalanceSerializer(many=True))
    def get(self, request: Request) -> Response:
        return Response(payee_balances(request.user.pk))


class MyPayoutsView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(responses=s.PayoutSerializer(many=True))
    def get(self, request: Request) -> Response:
        return _paginate(
            self, request, Payout.objects.filter(payee=request.user).order_by("-created_at"), s.PayoutSerializer
        )

    @extend_schema(request=s.PayoutCreateSerializer, responses={201: s.PayoutSerializer})
    @idempotent("payments.payout")
    def post(self, request: Request) -> Response:
        serializer = s.PayoutCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payout = services.request_payout(user=request.user, **serializer.validated_data)
        return Response(s.PayoutSerializer(payout).data, status=status.HTTP_201_CREATED)


class MyPayoutCancelView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(request=None, responses=s.PayoutSerializer)
    def post(self, request: Request, payout_id: Any) -> Response:
        return Response(s.PayoutSerializer(services.cancel_payout(user=request.user, payout_id=payout_id)).data)


class PayoutQueueView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(parameters=[OpenApiParameter("status", str)], responses=s.PayoutSerializer(many=True))
    def get(self, request: Request) -> Response:
        authorize(request.user, "payments.payouts.manage")
        qs = Payout.objects.filter(status=request.query_params.get("status") or "requested").order_by("created_at")
        return _paginate(self, request, qs, s.PayoutSerializer)


class PayoutDecisionView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    approve = True

    @extend_schema(request=s.PayoutDecisionSerializer, responses=s.PayoutSerializer)
    def post(self, request: Request, payout_id: Any) -> Response:
        serializer = s.PayoutDecisionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payout = services.decide_payout(
            actor=request.user, payout_id=payout_id, approve=self.approve, **serializer.validated_data
        )
        return Response(s.PayoutSerializer(payout).data)
