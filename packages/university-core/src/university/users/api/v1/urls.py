from __future__ import annotations

from django.urls import path

from university.users.api.v1 import views

app_name = "users"

urlpatterns = [
    # Public authentication flows
    path("auth/register/", views.RegisterView.as_view(), name="register"),
    path("auth/email/verify/", views.VerifyEmailView.as_view(), name="verify-email"),
    path("auth/email/verify/resend/", views.ResendVerificationView.as_view(), name="verify-email-resend"),
    path("auth/email/change/confirm/", views.EmailChangeConfirmView.as_view(), name="email-change-confirm"),
    path("auth/password/reset/", views.PasswordResetView.as_view(), name="password-reset"),
    path("auth/password/reset/confirm/", views.PasswordResetConfirmView.as_view(), name="password-reset-confirm"),
    # The authenticated user
    path("me/", views.MeView.as_view(), name="me"),
    path("me/password/", views.PasswordChangeView.as_view(), name="password-change"),
    path("me/email/", views.EmailChangeView.as_view(), name="email-change"),
    path("me/phone/", views.PhoneView.as_view(), name="phone"),
    path("me/phone/verify/", views.PhoneVerifyView.as_view(), name="phone-verify"),
    path("me/privacy/", views.PrivacySettingsView.as_view(), name="privacy-settings"),
    path("me/notifications/", views.NotificationSettingsView.as_view(), name="notification-settings"),
    path("me/security/", views.SecuritySettingsView.as_view(), name="security-settings"),
    path("me/consents/", views.ConsentView.as_view(), name="consents"),
    path("me/export/", views.DataExportView.as_view(), name="data-export"),
    # People
    path("users/<uuid:user_id>/", views.UserDetailView.as_view(), name="user-detail"),
    path("users/by-handle/<str:handle>/", views.UserByHandleView.as_view(), name="user-by-handle"),
    # Staff account management (authorised in services)
    path("users/<uuid:user_id>/suspend/", views.SuspendUserView.as_view(), name="user-suspend"),
    path("users/<uuid:user_id>/ban/", views.BanUserView.as_view(), name="user-ban"),
    path("users/<uuid:user_id>/reactivate/", views.ReactivateUserView.as_view(), name="user-reactivate"),
    path("users/<uuid:user_id>/restore/", views.RestoreUserView.as_view(), name="user-restore"),
]
