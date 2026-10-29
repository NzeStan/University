from django.contrib import admin

from university.subscriptions.models import Period, Subscription


class PeriodInline(admin.TabularInline):
    model = Period
    extra = 0
    can_delete = False
    readonly_fields = ("starts_at", "ends_at", "amount_minor", "currency", "payment_reference")


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = ("user", "plan", "interval", "status", "current_period_end", "cancel_at_period_end")
    list_filter = ("plan", "status", "interval")
    search_fields = ("user__handle", "user__email")
    readonly_fields = ("user", "current_period_start", "current_period_end", "reminded_for")
    inlines = [PeriodInline]
