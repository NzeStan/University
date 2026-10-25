from __future__ import annotations

from django.urls import path

from university.marketplace.api.v1 import views

app_name = "marketplace"

L = "listings/<uuid:listing_id>/"
ORD = "orders/<uuid:order_id>/"

urlpatterns = [
    path("categories/", views.CategoryListView.as_view(), name="category-list"),
    path("listings/", views.ListingListCreateView.as_view(), name="listing-list"),
    path(L, views.ListingDetailView.as_view(), name="listing-detail"),
    path(f"{L}status/", views.ListingStatusView.as_view(), name="listing-status"),
    path(f"{L}images/", views.ListingImageView.as_view(), name="listing-images"),
    path(f"{L}images/<uuid:image_id>/", views.ListingImageDetailView.as_view(), name="listing-image"),
    path("sellers/<str:lookup>/", views.SellerDetailView.as_view(), name="seller-detail"),
    path("sellers/<str:lookup>/reviews/", views.SellerReviewsView.as_view(), name="seller-reviews"),
    path("orders/", views.OrderCreateView.as_view(), name="order-create"),
    path(ORD, views.OrderDetailView.as_view(), name="order-detail"),
    path(f"{ORD}cancel/", views.order_action("cancel").as_view(), name="order-cancel"),
    path(f"{ORD}fulfil/", views.order_action("fulfil").as_view(), name="order-fulfil"),
    path(f"{ORD}confirm/", views.order_action("confirm").as_view(), name="order-confirm"),
    path(f"{ORD}complete/", views.order_action("complete").as_view(), name="order-complete"),
    path(f"{ORD}dispute/", views.order_action("dispute").as_view(), name="order-dispute"),
    path(f"{ORD}resolve/", views.OrderResolveView.as_view(), name="order-resolve"),
    path(f"{ORD}review/", views.OrderReviewView.as_view(), name="order-review"),
    path("reviews/<uuid:review_id>/reply/", views.ReviewReplyView.as_view(), name="review-reply"),
    path("disputes/", views.DisputeQueueView.as_view(), name="dispute-queue"),
    path("me/seller/", views.MySellerView.as_view(), name="my-seller"),
    path("me/listings/", views.MyListingsView.as_view(), name="my-listings"),
    path("me/orders/", views.MyOrdersView.as_view(), name="my-orders"),
]
