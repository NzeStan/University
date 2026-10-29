from __future__ import annotations

from typing import Any

from rest_framework import permissions, status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from university.core.api.pagination import PageNumberPagination
from university.core.api.schema import OpenApiParameter, extend_schema, paginated
from university.core.exceptions import AuthenticationFailed, NotFound
from university.core.idempotency import idempotent
from university.core.ids import is_valid_uuid
from university.marketplace import selectors, services
from university.marketplace.api.v1 import serializers as s
from university.marketplace.models import Listing, MarketCategory, Review, SellerProfile


def _paginate(view: APIView, request: Request, qs: Any, serializer: Any) -> Response:
    paginator = PageNumberPagination()
    page = paginator.paginate_queryset(qs, request, view=view)
    return paginator.get_paginated_response(serializer(page, many=True, context={"request": request}).data)


def _ctx(request: Request) -> dict[str, Any]:
    return {"request": request}


BROWSE_PARAMS = (
    "q",
    "category",
    "condition",
    "currency",
    "city",
    "scope_type",
    "scope_id",
    "seller",
    "min_price",
    "max_price",
    "in_stock",
    "sort",
)


class CategoryListView(APIView):
    permission_classes = [permissions.AllowAny]

    @extend_schema(responses=s.MarketCategorySerializer(many=True))
    def get(self, request: Request) -> Response:
        qs = MarketCategory.objects.filter(is_active=True).select_related("parent")
        return Response(s.MarketCategorySerializer(qs, many=True).data)


class ListingListCreateView(APIView):
    permission_classes = [permissions.AllowAny]

    @extend_schema(
        parameters=[OpenApiParameter(p, str) for p in BROWSE_PARAMS], responses=paginated(s.MarketListingSerializer)
    )
    def get(self, request: Request) -> Response:
        return _paginate(self, request, selectors.browse(request.user, request.query_params), s.MarketListingSerializer)

    @extend_schema(request=s.MarketListingWriteSerializer, responses={201: s.MarketListingSerializer})
    def post(self, request: Request) -> Response:
        if not request.user.is_authenticated:
            raise AuthenticationFailed()
        serializer = s.MarketListingWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        category = data.pop("category")
        scope_type, scope_id = data.pop("scope_type"), data.pop("scope_id")
        listing = services.create_listing(
            seller=request.user, data=data, category=category, scope_type=scope_type, scope_id=scope_id
        )
        return Response(s.MarketListingSerializer(listing, context=_ctx(request)).data, status=status.HTTP_201_CREATED)


class ListingDetailView(APIView):
    permission_classes = [permissions.AllowAny]

    @extend_schema(responses=s.MarketListingSerializer)
    def get(self, request: Request, listing_id: Any) -> Response:
        listing = selectors.get_visible_listing(request.user, listing_id)
        return Response(s.MarketListingSerializer(listing, context=_ctx(request)).data)

    @extend_schema(request=s.MarketListingWriteSerializer, responses=s.MarketListingSerializer)
    def patch(self, request: Request, listing_id: Any) -> Response:
        if not request.user.is_authenticated:
            raise AuthenticationFailed()
        selectors.get_visible_listing(request.user, listing_id)
        serializer = s.MarketListingWriteSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        data = {k: v for k, v in serializer.validated_data.items() if k not in ("scope_type", "scope_id")}
        category = data.pop("category", None)
        listing = services.update_listing(user=request.user, listing_id=listing_id, data=data, category=category)
        return Response(s.MarketListingSerializer(listing, context=_ctx(request)).data)


class ListingStatusView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(request=s.MarketListingActionSerializer, responses=s.MarketListingSerializer)
    def post(self, request: Request, listing_id: Any) -> Response:
        selectors.get_visible_listing(request.user, listing_id)
        serializer = s.MarketListingActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        listing = services.set_listing_status(user=request.user, listing_id=listing_id, **serializer.validated_data)
        return Response(s.MarketListingSerializer(listing, context=_ctx(request)).data)


class ListingImageView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    @extend_schema(request=s.MarketImageUploadSerializer, responses={201: s.MarketImageSerializer})
    def post(self, request: Request, listing_id: Any) -> Response:
        selectors.get_visible_listing(request.user, listing_id)
        serializer = s.MarketImageUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        image = services.add_image(user=request.user, listing_id=listing_id, **serializer.validated_data)
        return Response(s.MarketImageSerializer(image, context=_ctx(request)).data, status=status.HTTP_201_CREATED)


class ListingImageDetailView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(responses={204: None})
    def delete(self, request: Request, listing_id: Any, image_id: Any) -> Response:
        services.remove_image(user=request.user, listing_id=listing_id, image_id=image_id)
        return Response(status=status.HTTP_204_NO_CONTENT)


class MyListingsView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(responses=paginated(s.MarketListingSerializer))
    def get(self, request: Request) -> Response:
        qs = Listing.objects.filter(seller=request.user).select_related("category", "seller").order_by("-created_at")
        return _paginate(self, request, qs, s.MarketListingSerializer)


class SellerDetailView(APIView):
    permission_classes = [permissions.AllowAny]

    def _profile(self, request: Request, lookup: str) -> SellerProfile:
        qs = SellerProfile.objects.select_related("user")
        profile = (
            qs.filter(user_id=lookup).first()
            if is_valid_uuid(lookup)
            else qs.filter(user__handle=lookup.lower()).first()
        )
        if profile is None or not profile.user.is_active or not selectors.not_blocked(request.user, profile.user):
            raise NotFound("Seller not found.")
        return profile

    @extend_schema(responses=s.MarketSellerSerializer)
    def get(self, request: Request, lookup: str) -> Response:
        return Response(s.MarketSellerSerializer(self._profile(request, lookup)).data)


class SellerReviewsView(SellerDetailView):
    @extend_schema(responses=paginated(s.MarketReviewSerializer))
    def get(self, request: Request, lookup: str) -> Response:
        profile = self._profile(request, lookup)
        qs = (
            Review.objects.filter(seller=profile.user, hidden_at__isnull=True)
            .select_related("reviewer")
            .order_by("-created_at")
        )
        return _paginate(self, request, qs, s.MarketReviewSerializer)


class MySellerView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(responses=s.MarketSellerSerializer)
    def get(self, request: Request) -> Response:
        return Response(s.MarketSellerSerializer(services.seller_profile(request.user)).data)

    @extend_schema(request=s.MarketSellerWriteSerializer, responses=s.MarketSellerSerializer)
    def patch(self, request: Request) -> Response:
        serializer = s.MarketSellerWriteSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        return Response(
            s.MarketSellerSerializer(
                services.update_seller_profile(user=request.user, data=serializer.validated_data)
            ).data
        )


class OrderCreateView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        request=s.MarketOrderCreateSerializer,
        responses={201: s.MarketOrderSerializer},
        parameters=[OpenApiParameter("Idempotency-Key", str, location=OpenApiParameter.HEADER, required=True)],
    )
    @idempotent("marketplace.order.create", required=True)
    def post(self, request: Request) -> Response:
        serializer = s.MarketOrderCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        order = services.place_order(buyer=request.user, listing_id=data.pop("listing"), **data)
        return Response(s.MarketOrderSerializer(order, context=_ctx(request)).data, status=status.HTTP_201_CREATED)


class OrderDetailView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(responses=s.MarketOrderSerializer)
    def get(self, request: Request, order_id: Any) -> Response:
        return Response(
            s.MarketOrderSerializer(selectors.get_order_for(request.user, order_id), context=_ctx(request)).data
        )


def order_action(name: str) -> type[APIView]:
    actions = {
        "cancel": lambda r, oid, d: services.cancel_order(user=r.user, order_id=oid, reason=d.get("reason", "")),
        "fulfil": lambda r, oid, d: services.fulfil_order(user=r.user, order_id=oid),
        "confirm": lambda r, oid, d: services.confirm_received(user=r.user, order_id=oid),
        "complete": lambda r, oid, d: services.complete_cash_order(user=r.user, order_id=oid),
        "dispute": lambda r, oid, d: services.open_dispute(user=r.user, order_id=oid, reason=d.get("reason", "")),
    }
    action = actions[name]

    class OrderActionView(APIView):
        permission_classes = [permissions.IsAuthenticated]

        @extend_schema(
            request=s.MarketReasonSerializer,
            responses=s.MarketOrderSerializer,
            operation_id=f"marketplace_order_{name}",
        )
        def post(self, request: Request, order_id: Any) -> Response:
            serializer = s.MarketReasonSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            order = action(request, order_id, serializer.validated_data)
            return Response(s.MarketOrderSerializer(order, context=_ctx(request)).data)

    OrderActionView.__name__ = f"Order{name.title()}View"
    return OrderActionView


class OrderResolveView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(request=s.MarketResolveSerializer, responses=s.MarketOrderSerializer)
    def post(self, request: Request, order_id: Any) -> Response:
        serializer = s.MarketResolveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        order = services.resolve_dispute(actor=request.user, order_id=order_id, **serializer.validated_data)
        return Response(s.MarketOrderSerializer(order, context=_ctx(request)).data)


class OrderReviewView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(request=s.MarketReviewCreateSerializer, responses={201: s.MarketReviewSerializer})
    def post(self, request: Request, order_id: Any) -> Response:
        serializer = s.MarketReviewCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        review = services.create_review(user=request.user, order_id=order_id, **serializer.validated_data)
        return Response(s.MarketReviewSerializer(review).data, status=status.HTTP_201_CREATED)


class ReviewReplyView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(request=s.MarketReplySerializer, responses=s.MarketReviewSerializer)
    def post(self, request: Request, review_id: Any) -> Response:
        serializer = s.MarketReplySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        review = services.reply_to_review(
            user=request.user, review_id=review_id, reply=serializer.validated_data["reply"]
        )
        return Response(s.MarketReviewSerializer(review).data)


class MyOrdersView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        parameters=[OpenApiParameter("role", str, enum=["buyer", "seller"])],
        responses=paginated(s.MarketOrderSerializer),
    )
    def get(self, request: Request) -> Response:
        role = request.query_params.get("role") or "buyer"
        return _paginate(self, request, selectors.my_orders(request.user, role), s.MarketOrderSerializer)


class DisputeQueueView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(responses=paginated(s.MarketOrderSerializer))
    def get(self, request: Request) -> Response:
        return _paginate(self, request, services.disputes_queue(request.user), s.MarketOrderSerializer)
