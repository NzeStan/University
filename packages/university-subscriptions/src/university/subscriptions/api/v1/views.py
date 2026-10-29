from __future__ import annotations

from rest_framework import permissions, status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from university.core.api.schema import extend_schema
from university.core.entitlements import entitlements
from university.subscriptions import services
from university.subscriptions.api.v1 import serializers as s
from university.subscriptions.conf import plans


class PlanListView(APIView):
    permission_classes = [permissions.AllowAny]

    @extend_schema(responses=s.SubscriptionPlanSerializer(many=True))
    def get(self, request: Request) -> Response:
        return Response([s.plan_data(key, plan) for key, plan in plans().items()])


class MySubscriptionView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def _body(self, request: Request) -> dict:
        sub = services.current(request.user)
        return {
            "subscription": s.SubscriptionSerializer(sub).data if sub else None,
            "entitlements": sorted(entitlements(request.user)),
        }

    @extend_schema(responses=s.MySubscriptionSerializer)
    def get(self, request: Request) -> Response:
        return Response(self._body(request))

    @extend_schema(
        request=s.SubscribeSerializer,
        responses={201: s.SubscriptionSerializer},
        description="Choose a plan. Then pay `payment_due` through POST /payments/checkout/.",
    )
    def post(self, request: Request) -> Response:
        serializer = s.SubscribeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        sub = services.subscribe(user=request.user, **serializer.validated_data)
        return Response(s.SubscriptionSerializer(sub).data, status=status.HTTP_201_CREATED)

    @extend_schema(responses={204: None}, description="Drop a subscription that hasn't been paid for yet.")
    def delete(self, request: Request) -> Response:
        services.abandon(user=request.user)
        return Response(status=status.HTTP_204_NO_CONTENT)


class CancelView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        request=s.CancelSerializer,
        responses=s.SubscriptionSerializer,
        description="Stop renewing: the plan stays until the paid period ends. Send cancel=false to undo.",
    )
    def post(self, request: Request) -> Response:
        serializer = s.CancelSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        sub = services.set_cancel_at_period_end(user=request.user, cancel=serializer.validated_data["cancel"])
        return Response(s.SubscriptionSerializer(sub).data)
