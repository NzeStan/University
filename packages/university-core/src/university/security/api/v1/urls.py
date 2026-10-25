from __future__ import annotations

from django.urls import path

from university.security.api.v1 import views

app_name = "security"

urlpatterns = [
    path("auth/login/", views.LoginView.as_view(), name="login"),
    path("auth/login/mfa/", views.MFALoginView.as_view(), name="login-mfa"),
    path("auth/token/refresh/", views.TokenRefreshView.as_view(), name="token-refresh"),
    path("auth/logout/", views.LogoutView.as_view(), name="logout"),
    path("auth/passwordless/", views.PasswordlessRequestView.as_view(), name="passwordless-request"),
    path("auth/passwordless/verify/", views.PasswordlessVerifyView.as_view(), name="passwordless-verify"),
    path("auth/providers/<slug:provider>/login/", views.ProviderLoginView.as_view(), name="provider-login"),
    path("me/sessions/", views.SessionListView.as_view(), name="session-list"),
    path("me/sessions/revoke-others/", views.RevokeOtherSessionsView.as_view(), name="session-revoke-others"),
    path("me/sessions/<uuid:session_id>/", views.SessionDetailView.as_view(), name="session-detail"),
    path("me/api-keys/", views.APIKeyListCreateView.as_view(), name="api-key-list"),
    path("me/api-keys/<uuid:api_key_id>/", views.APIKeyDetailView.as_view(), name="api-key-detail"),
    path("me/identities/", views.ExternalIdentityListView.as_view(), name="identity-list"),
    path("me/identities/<uuid:identity_id>/", views.ExternalIdentityDetailView.as_view(), name="identity-detail"),
    path("me/identities/<slug:provider>/link/", views.ExternalIdentityLinkView.as_view(), name="identity-link"),
    path("me/mfa/enrol/", views.MFAEnrolView.as_view(), name="mfa-enrol"),
    path("me/mfa/confirm/", views.MFAConfirmView.as_view(), name="mfa-confirm"),
    path("me/mfa/disable/", views.MFADisableView.as_view(), name="mfa-disable"),
]
