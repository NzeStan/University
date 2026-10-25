"""Marketplace data model.

::

    MarketCategory (tree)
    SellerProfile
    Listing ──┬── ListingImage
              └── Order ── Review

Inventory is a counter on the listing, changed only under a row lock and
guarded by a check constraint, so stock can't go negative. Orders keep a
snapshot of what was bought (title, unit price), so later listing edits never
change past orders.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models
from django.db.models import F, Q
from django.utils.translation import gettext_lazy as _

from university.core.models import BaseModel, SoftDeleteModel
from university.core.uploads import uuid_upload_to
from university.marketplace.constants import (
    Condition,
    Fulfilment,
    ListingStatus,
    ListingVisibility,
    OrderStatus,
    PaymentMethod,
)

USER = settings.AUTH_USER_MODEL


class MarketCategory(models.Model):
    key = models.SlugField(max_length=40, unique=True)
    name = models.CharField(max_length=80)
    parent = models.ForeignKey("self", null=True, blank=True, on_delete=models.CASCADE, related_name="children")
    is_active = models.BooleanField(default=True)
    position = models.PositiveSmallIntegerField(default=0)

    class Meta:
        verbose_name = _("market category")
        verbose_name_plural = _("market categories")
        ordering = ("position", "name")

    def __str__(self) -> str:
        return self.name


class SellerProfile(BaseModel):
    user = models.OneToOneField(USER, on_delete=models.CASCADE, related_name="seller_profile")
    store_name = models.CharField(max_length=80)
    about = models.TextField(blank=True)
    rating_sum = models.PositiveIntegerField(default=0)
    rating_count = models.PositiveIntegerField(default=0)
    sales_count = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = _("seller profile")

    def __str__(self) -> str:
        return self.store_name

    @property
    def rating(self) -> float | None:
        return round(self.rating_sum / self.rating_count, 2) if self.rating_count else None


class Listing(BaseModel, SoftDeleteModel):
    seller = models.ForeignKey(USER, on_delete=models.CASCADE, related_name="market_listings")
    title = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    category = models.ForeignKey(MarketCategory, on_delete=models.PROTECT, related_name="listings")
    condition = models.CharField(max_length=16, choices=Condition.choices, default=Condition.USED)
    price_minor = models.PositiveBigIntegerField()
    currency = models.CharField(max_length=3, default="NGN")
    quantity = models.PositiveIntegerField(default=1)
    status = models.CharField(max_length=16, choices=ListingStatus.choices, default=ListingStatus.DRAFT)
    visibility = models.CharField(max_length=16, choices=ListingVisibility.choices, default=ListingVisibility.PUBLIC)
    #: Optional scope (e.g. an institution's marketplace).
    scope_type = models.CharField(max_length=32, blank=True)
    scope_id = models.CharField(max_length=64, blank=True)
    city = models.CharField(max_length=100, blank=True)
    location_note = models.CharField(max_length=160, blank=True, help_text=_("e.g. 'Faculty of Science gate'"))
    allows_pickup = models.BooleanField(default=True)
    allows_delivery = models.BooleanField(default=False)
    delivery_fee_minor = models.PositiveBigIntegerField(default=0)
    allows_cash_on_pickup = models.BooleanField(default=True)
    published_at = models.DateTimeField(null=True, blank=True)
    hidden_at = models.DateTimeField(null=True, blank=True)
    hidden_reason = models.CharField(max_length=255, blank=True)

    class Meta:
        verbose_name = _("listing")
        indexes = [
            models.Index(fields=["status", "visibility", "-published_at"], name="univ_mkt_listing_browse"),
            models.Index(fields=["category", "status"], name="univ_mkt_listing_category"),
            models.Index(fields=["seller", "status"], name="univ_mkt_listing_seller"),
            models.Index(fields=["scope_type", "scope_id"], name="univ_mkt_listing_scope"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=(Q(scope_type="") & Q(scope_id="")) | (~Q(scope_type="") & ~Q(scope_id="")),
                name="univ_mkt_listing_scope_consistent",
            ),
            models.CheckConstraint(
                condition=~Q(visibility=ListingVisibility.AUDIENCE) | ~Q(scope_type=""),
                name="univ_mkt_audience_needs_scope",
            ),
            models.CheckConstraint(
                condition=Q(allows_pickup=True) | Q(allows_delivery=True), name="univ_mkt_fulfilment"
            ),
        ]

    def __str__(self) -> str:
        return self.title

    @property
    def listing_scope(self) -> tuple[str, str] | None:
        return (self.scope_type, self.scope_id) if self.scope_type else None


class ListingImage(BaseModel):
    listing = models.ForeignKey(Listing, on_delete=models.CASCADE, related_name="images")
    file = models.FileField(upload_to=uuid_upload_to("marketplace/listings"), max_length=255)
    alt_text = models.CharField(max_length=200, blank=True)
    position = models.PositiveSmallIntegerField(default=0)

    class Meta:
        verbose_name = _("listing image")
        ordering = ("position", "created_at")

    def __str__(self) -> str:
        return f"Image of {self.listing_id}"


class Order(BaseModel):
    reference = models.CharField(max_length=40, unique=True)
    buyer = models.ForeignKey(USER, null=True, on_delete=models.SET_NULL, related_name="market_orders")
    seller = models.ForeignKey(USER, null=True, on_delete=models.SET_NULL, related_name="market_sales")
    listing = models.ForeignKey(Listing, null=True, on_delete=models.SET_NULL, related_name="orders")
    # Snapshot of what was bought.
    title = models.CharField(max_length=120)
    unit_price_minor = models.PositiveBigIntegerField()
    quantity = models.PositiveIntegerField()
    delivery_fee_minor = models.PositiveBigIntegerField(default=0)
    total_minor = models.PositiveBigIntegerField()
    currency = models.CharField(max_length=3)
    platform_fee_minor = models.PositiveBigIntegerField(default=0)
    fulfilment = models.CharField(max_length=16, choices=Fulfilment.choices)
    payment_method = models.CharField(max_length=16, choices=PaymentMethod.choices)
    #: Address / phone for the handover. Visible to buyer and seller only; erased after closing.
    delivery_details = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=OrderStatus.choices)
    payment_reference = models.CharField(max_length=64, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    fulfilled_at = models.DateTimeField(null=True, blank=True)
    auto_complete_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    cancel_reason = models.CharField(max_length=255, blank=True)
    disputed_at = models.DateTimeField(null=True, blank=True)
    dispute_reason = models.TextField(blank=True)
    resolution = models.CharField(max_length=500, blank=True)
    resolved_by = models.ForeignKey(USER, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    #: Restocked already (guards double restocking).
    restocked = models.BooleanField(default=False)

    class Meta:
        verbose_name = _("order")
        indexes = [
            models.Index(fields=["buyer", "-created_at"], name="univ_mkt_order_buyer"),
            models.Index(fields=["seller", "status"], name="univ_mkt_order_seller"),
            models.Index(fields=["status", "expires_at"], name="univ_mkt_order_expiry"),
            models.Index(fields=["status", "auto_complete_at"], name="univ_mkt_order_autocomplete"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(total_minor=F("unit_price_minor") * F("quantity") + F("delivery_fee_minor")),
                name="univ_mkt_order_total",
            ),
            models.CheckConstraint(condition=Q(quantity__gte=1), name="univ_mkt_order_quantity"),
            models.CheckConstraint(condition=Q(platform_fee_minor__lte=F("total_minor")), name="univ_mkt_order_fee"),
        ]

    def __str__(self) -> str:
        return self.reference


class Review(BaseModel):
    order = models.OneToOneField(Order, on_delete=models.CASCADE, related_name="review")
    reviewer = models.ForeignKey(USER, null=True, on_delete=models.SET_NULL, related_name="+")
    seller = models.ForeignKey(USER, on_delete=models.CASCADE, related_name="market_reviews")
    listing = models.ForeignKey(Listing, null=True, on_delete=models.SET_NULL, related_name="reviews")
    rating = models.PositiveSmallIntegerField()
    comment = models.TextField(blank=True)
    seller_reply = models.TextField(blank=True)
    replied_at = models.DateTimeField(null=True, blank=True)
    hidden_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = _("review")
        constraints = [models.CheckConstraint(condition=Q(rating__gte=1, rating__lte=5), name="univ_mkt_rating_range")]
        indexes = [models.Index(fields=["seller", "-created_at"], name="univ_mkt_review_seller")]

    def __str__(self) -> str:
        return f"{self.rating}★ for {self.seller_id}"
