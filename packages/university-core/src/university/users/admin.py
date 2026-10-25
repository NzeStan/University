from __future__ import annotations

from typing import Any

from django import forms
from django.contrib import admin, messages
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.contrib.auth.forms import ReadOnlyPasswordHashField

from university.core.exceptions import UniversityError
from university.users import services
from university.users.models import ConsentRecord, NotificationSettings, PrivacySettings, SecuritySettings

User = get_user_model()


class UserCreationForm(forms.ModelForm):
    password1 = forms.CharField(label="Password", widget=forms.PasswordInput)
    password2 = forms.CharField(label="Password confirmation", widget=forms.PasswordInput)

    class Meta:
        model = User
        fields = ("email", "handle", "display_name")

    def clean_password2(self) -> str:
        p1, p2 = self.cleaned_data.get("password1"), self.cleaned_data.get("password2")
        if p1 and p2 and p1 != p2:
            raise forms.ValidationError("Passwords don't match.")
        return p2 or ""

    def save(self, commit: bool = True) -> Any:
        user = super().save(commit=False)
        user.set_password(self.cleaned_data["password1"])
        if commit:
            user.save()
            services.ensure_user_settings(user)
        return user


class UserChangeForm(forms.ModelForm):
    password = ReadOnlyPasswordHashField(help_text="Raw passwords are not stored.")

    class Meta:
        model = User
        fields = ("email", "handle", "display_name", "password", "is_staff", "is_superuser", "groups")


class PrivacyInline(admin.StackedInline):
    model = PrivacySettings
    can_delete = False
    extra = 0


class SecurityInline(admin.StackedInline):
    model = SecuritySettings
    can_delete = False
    extra = 0
    readonly_fields = ("mfa_enabled", "mfa_channel", "mfa_enabled_at")


class UserAdmin(DjangoUserAdmin):
    """Account administration. Status changes go through audited services."""

    form = UserChangeForm
    add_form = UserCreationForm
    ordering = ("-created_at",)
    list_display = ("email", "handle", "display_name", "status", "is_staff", "email_verified_at", "created_at")
    list_filter = ("status", "is_staff", "is_superuser")
    search_fields = ("email", "handle", "display_name")
    readonly_fields = (
        "id",
        "status",
        "status_reason",
        "status_changed_at",
        "suspended_until",
        "email_verified_at",
        "phone_number",
        "phone_verified_at",
        "last_login",
        "created_at",
        "deleted_at",
        "anonymized_at",
        "password_changed_at",
    )
    fieldsets = (
        (None, {"fields": ("id", "email", "password")}),
        ("Profile", {"fields": ("handle", "display_name", "phone_number", "phone_verified_at", "email_verified_at")}),
        ("Status", {"fields": ("status", "status_reason", "status_changed_at", "suspended_until")}),
        ("Permissions", {"fields": ("is_staff", "is_superuser", "groups")}),
        ("Dates", {"fields": ("last_login", "created_at", "password_changed_at", "deleted_at", "anonymized_at")}),
    )
    add_fieldsets = (
        (None, {"classes": ("wide",), "fields": ("email", "handle", "display_name", "password1", "password2")}),
    )
    filter_horizontal = ("groups",)
    inlines = (PrivacyInline, SecurityInline)
    actions = ["suspend_users", "ban_users", "reactivate_users"]

    def get_queryset(self, request: Any) -> Any:
        return User.all_objects.all()

    def get_readonly_fields(self, request: Any, obj: Any = None) -> Any:
        fields = list(super().get_readonly_fields(request, obj))
        if not request.user.is_superuser:
            fields += ["is_staff", "is_superuser", "groups"]
        return fields

    def _run(self, request: Any, queryset: Any, func: Any, **kwargs: Any) -> None:
        done = 0
        for user in queryset:
            try:
                func(actor=request.user, user=user, **kwargs)
                done += 1
            except UniversityError as exc:
                self.message_user(request, f"{user}: {exc.message}", messages.ERROR)
        if done:
            self.message_user(request, f"Updated {done} account(s).", messages.SUCCESS)

    @admin.action(description="Suspend selected accounts")
    def suspend_users(self, request: Any, queryset: Any) -> None:
        self._run(request, queryset, services.suspend_user, reason="Suspended via admin")

    @admin.action(description="Ban selected accounts")
    def ban_users(self, request: Any, queryset: Any) -> None:
        self._run(request, queryset, services.ban_user, reason="Banned via admin")

    @admin.action(description="Reactivate selected accounts")
    def reactivate_users(self, request: Any, queryset: Any) -> None:
        self._run(request, queryset, services.reactivate_user)


if not admin.site.is_registered(User) and User._meta.app_label == "university_users":
    admin.site.register(User, UserAdmin)


@admin.register(ConsentRecord)
class ConsentRecordAdmin(admin.ModelAdmin):
    list_display = ("user", "purpose", "granted", "version", "created_at")
    list_filter = ("purpose", "granted")
    raw_id_fields = ("user",)

    def has_change_permission(self, request: Any, obj: Any = None) -> bool:
        return False


admin.site.register(NotificationSettings, admin.ModelAdmin)
