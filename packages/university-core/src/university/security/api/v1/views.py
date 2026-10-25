from __future__ import annotations

from typing import Any

from rest_framework import permissions, status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from university.core.api.schema import extend_schema
from university.core.api.serializers import ChallengeSerializer, CountSerializer
from university.core.exceptions import AuthenticationFailed, ValidationError
from university.core.http import ClientMeta
from university.security.api.v1 import serializers as s
from university.security.models import APIKey, ExternalIdentity, UserSession
from university.security.services import api_keys, external, login, mfa, sessions
from university.security.services.login import LoginResult


def _meta(request: Request, data: dict[str, Any]) -> ClientMeta:
    return ClientMeta.from_request(
        request, device_id=data.get("device_id", ""), device_name=data.get("device_name", "")
    )


def _current_session(request: Request) -> Any:
    return getattr(getattr(request, "auth", None), "session", None)


def _login_response(result: LoginResult) -> Response:
    if result.mfa_required and result.challenge is not None:
        return Response(
            {
                "mfa_required": True,
                "challenge_id": str(result.challenge.pk),
                "channel": result.challenge.channel,
                "destination": result.challenge.destination_masked,
            },
            status=status.HTTP_202_ACCEPTED,
        )
    if result.tokens is None:  # pragma: no cover - services always return tokens or a challenge
        raise AuthenticationFailed()
    return Response(result.tokens.as_dict(), status=status.HTTP_200_OK)


class PublicAPIView(APIView):
    """Unauthenticated endpoint: no credentials are read, so CSRF does not apply."""

    authentication_classes: list[Any] = []
    permission_classes = [permissions.AllowAny]


# ------------------------------------------------------------------ login
class LoginView(PublicAPIView):
    throttle_scope = "login"

    @extend_schema(request=s.LoginSerializer, responses={200: s.TokenPairSerializer, 202: s.MFAChallengeSerializer})
    def post(self, request: Request) -> Response:
        serializer = s.LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        result = login.login_with_password(
            identifier=data["identifier"], password=data["password"], meta=_meta(request, data)
        )
        return _login_response(result)


class MFALoginView(PublicAPIView):
    throttle_scope = "otp_verify"

    @extend_schema(request=s.ChallengeCompleteSerializer, responses=s.TokenPairSerializer)
    def post(self, request: Request) -> Response:
        serializer = s.ChallengeCompleteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        result = login.complete_mfa_login(
            challenge_id=data["challenge_id"], code=data["code"], meta=_meta(request, data)
        )
        return _login_response(result)


class TokenRefreshView(PublicAPIView):
    throttle_scope = "token_refresh"

    @extend_schema(request=s.RefreshSerializer, responses=s.TokenPairSerializer)
    def post(self, request: Request) -> Response:
        serializer = s.RefreshSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        tokens = sessions.rotate_refresh_token(serializer.validated_data["refresh"], meta=_meta(request, {}))
        return Response(tokens.as_dict())


class LogoutView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(request=None, responses={204: None})
    def post(self, request: Request) -> Response:
        session = _current_session(request)
        if session is not None:
            sessions.logout(session, user=request.user)
        return Response(status=status.HTTP_204_NO_CONTENT)


class PasswordlessRequestView(PublicAPIView):
    throttle_scope = "otp_request"

    @extend_schema(request=s.PasswordlessRequestSerializer, responses={202: ChallengeSerializer})
    def post(self, request: Request) -> Response:
        serializer = s.PasswordlessRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        challenge = login.request_passwordless_code(
            identifier=serializer.validated_data["identifier"], meta=_meta(request, {})
        )
        return Response(
            {"challenge_id": str(challenge.challenge_id), "channel": challenge.channel},
            status=status.HTTP_202_ACCEPTED,
        )


class PasswordlessVerifyView(PublicAPIView):
    throttle_scope = "otp_verify"

    @extend_schema(request=s.ChallengeCompleteSerializer, responses=s.TokenPairSerializer)
    def post(self, request: Request) -> Response:
        serializer = s.ChallengeCompleteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        result = login.complete_passwordless_login(
            challenge_id=data["challenge_id"], code=data["code"], meta=_meta(request, data)
        )
        return _login_response(result)


class ProviderLoginView(PublicAPIView):
    throttle_scope = "login"

    @extend_schema(request=s.ProviderLoginSerializer, responses=s.TokenPairSerializer)
    def post(self, request: Request, provider: str) -> Response:
        serializer = s.ProviderLoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        result = external.login_with_provider(provider, data, meta=_meta(request, data))
        return _login_response(result)


# --------------------------------------------------------------- sessions
class SessionListView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(responses=s.SessionSerializer(many=True))
    def get(self, request: Request) -> Response:
        qs = UserSession.objects.active().filter(user=request.user).order_by("-last_seen_at")[:100]
        current = _current_session(request)
        context = {"current_session_id": getattr(current, "pk", None)}
        return Response(s.SessionSerializer(qs, many=True, context=context).data)


class SessionDetailView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(responses={204: None})
    def delete(self, request: Request, session_id: Any) -> Response:
        sessions.revoke_user_session(request.user, session_id)
        return Response(status=status.HTTP_204_NO_CONTENT)


class RevokeOtherSessionsView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(request=None, responses=CountSerializer)
    def post(self, request: Request) -> Response:
        current = _current_session(request)
        count = sessions.revoke_user_sessions(
            request.user,
            actor=request.user,
            reason="revoked_by_user",
            except_session_id=getattr(current, "pk", None),
        )
        return Response({"revoked": count})


# --------------------------------------------------------------- API keys
class APIKeyListCreateView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @property
    def throttle_scope(self) -> str | None:  # type: ignore[override]
        return "api_key_create" if self.request.method == "POST" else None

    @extend_schema(responses=s.APIKeySerializer(many=True))
    def get(self, request: Request) -> Response:
        qs = APIKey.objects.filter(user=request.user).order_by("-created_at")
        return Response(s.APIKeySerializer(qs, many=True).data)

    @extend_schema(request=s.APIKeyCreateSerializer, responses={201: s.APIKeyCreatedSerializer})
    def post(self, request: Request) -> Response:
        if getattr(getattr(request, "auth", None), "is_api_key", False):
            raise ValidationError("API keys cannot create other API keys.", code="api_key_forbidden")
        serializer = s.APIKeyCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        created = api_keys.create_api_key(request.user, **serializer.validated_data)
        data = s.APIKeyCreatedSerializer(created.api_key, context={"raw_key": created.raw_key}).data
        return Response(data, status=status.HTTP_201_CREATED)


class APIKeyDetailView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(responses={204: None})
    def delete(self, request: Request, api_key_id: Any) -> Response:
        api_keys.revoke_api_key(request.user, api_key_id)
        return Response(status=status.HTTP_204_NO_CONTENT)


# ------------------------------------------------------ external identity
class ExternalIdentityListView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(responses=s.ExternalIdentitySerializer(many=True))
    def get(self, request: Request) -> Response:
        qs = ExternalIdentity.objects.filter(user=request.user)
        return Response(s.ExternalIdentitySerializer(qs, many=True).data)


class ExternalIdentityLinkView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(request=s.ProviderLoginSerializer, responses={201: s.ExternalIdentitySerializer})
    def post(self, request: Request, provider: str) -> Response:
        serializer = s.ProviderLoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        identity = external.link_provider(request.user, provider, serializer.validated_data)
        return Response(s.ExternalIdentitySerializer(identity).data, status=status.HTTP_201_CREATED)


class ExternalIdentityDetailView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(responses={204: None})
    def delete(self, request: Request, identity_id: Any) -> Response:
        external.unlink_provider(request.user, identity_id)
        return Response(status=status.HTTP_204_NO_CONTENT)


# -------------------------------------------------------------------- MFA
class MFAEnrolView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    throttle_scope = "otp_request"

    @extend_schema(request=s.MFAEnrolSerializer, responses={202: ChallengeSerializer})
    def post(self, request: Request) -> Response:
        serializer = s.MFAEnrolSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        challenge = mfa.start_mfa_enrolment(request.user, channel=serializer.validated_data["channel"])
        return Response(
            {"challenge_id": str(challenge.pk), "destination": challenge.destination_masked},
            status=status.HTTP_202_ACCEPTED,
        )


class MFAConfirmView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    throttle_scope = "otp_verify"

    @extend_schema(request=s.MFAConfirmSerializer, responses={204: None})
    def post(self, request: Request) -> Response:
        serializer = s.MFAConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        mfa.confirm_mfa_enrolment(request.user, current_session=_current_session(request), **serializer.validated_data)
        return Response(status=status.HTTP_204_NO_CONTENT)


class MFADisableView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    throttle_scope = "password_change"

    @extend_schema(request=s.PasswordConfirmSerializer, responses={204: None})
    def post(self, request: Request) -> Response:
        serializer = s.PasswordConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        mfa.disable_mfa(request.user, password=serializer.validated_data["password"])
        return Response(status=status.HTTP_204_NO_CONTENT)
