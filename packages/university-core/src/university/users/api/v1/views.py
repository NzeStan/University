from __future__ import annotations

from typing import Any

from django.contrib.auth import get_user_model
from django.utils.module_loading import import_string
from rest_framework import permissions, status
from rest_framework.parsers import MultiPartParser
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from university.core.api.schema import OpenApiTypes, extend_schema
from university.core.api.serializers import ChallengeSerializer, DetailSerializer
from university.core.conf import university_settings
from university.core.exceptions import NotFound
from university.core.http import ClientMeta
from university.users import selectors, services
from university.users.api.v1 import serializers as s
from university.users.constants import RegistrationMode

GENERIC_ACCEPTED = "If the details are valid, we've sent you an email with the next steps."


def _serializer_class(setting: str, default: type) -> type:
    path = university_settings.get(f"USERS.{setting}")
    return import_string(path) if path else default


def me_serializer_class() -> type:
    return _serializer_class("ME_SERIALIZER", s.MeSerializer)


def public_profile_serializer_class() -> type:
    return _serializer_class("PUBLIC_PROFILE_SERIALIZER", s.PublicProfileSerializer)


class PublicAPIView(APIView):
    authentication_classes: list[Any] = []
    permission_classes = [permissions.AllowAny]


# -------------------------------------------------------------- register
class RegisterView(PublicAPIView):
    throttle_scope = "registration"

    @extend_schema(request=s.RegisterSerializer, responses={201: s.RegisteredSerializer, 202: DetailSerializer})
    def post(self, request: Request) -> Response:
        serializer = s.RegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        meta = ClientMeta.from_request(
            request, device_id=data.get("device_id", ""), device_name=data.get("device_name", "")
        )
        result = services.register_user(
            email=data["email"],
            password=data["password"],
            handle=data.get("handle") or None,
            display_name=data.get("display_name", ""),
            consents=data.get("consents"),
            consent_version=data.get("consent_version", ""),
            meta=meta,
        )
        if result.mode == RegistrationMode.VERIFY_FIRST:
            return Response({"detail": GENERIC_ACCEPTED}, status=status.HTTP_202_ACCEPTED)
        from university.security.services.sessions import create_session

        _, tokens = create_session(result.user, meta=meta, auth_method="registration")
        body = {"user": me_serializer_class()(result.user).data, "tokens": tokens.as_dict()}
        return Response(body, status=status.HTTP_201_CREATED)


class VerifyEmailView(PublicAPIView):
    throttle_scope = "email_verification"

    @extend_schema(request=s.TokenSerializer, responses=DetailSerializer)
    def post(self, request: Request) -> Response:
        serializer = s.TokenSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.verify_email(serializer.validated_data["token"])
        return Response({"detail": "Email address verified."})


class ResendVerificationView(PublicAPIView):
    throttle_scope = "email_verification"

    @extend_schema(request=s.EmailSerializer, responses=DetailSerializer)
    def post(self, request: Request) -> Response:
        serializer = s.EmailSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.resend_verification_email(serializer.validated_data["email"])
        return Response({"detail": GENERIC_ACCEPTED}, status=status.HTTP_202_ACCEPTED)


class PasswordResetView(PublicAPIView):
    throttle_scope = "password_reset"

    @extend_schema(request=s.EmailSerializer, responses=DetailSerializer)
    def post(self, request: Request) -> Response:
        serializer = s.EmailSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.request_password_reset(serializer.validated_data["email"])
        return Response({"detail": GENERIC_ACCEPTED}, status=status.HTTP_202_ACCEPTED)


class PasswordResetConfirmView(PublicAPIView):
    throttle_scope = "password_reset"

    @extend_schema(request=s.PasswordResetConfirmSerializer, responses=DetailSerializer)
    def post(self, request: Request) -> Response:
        serializer = s.PasswordResetConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.confirm_password_reset(**serializer.validated_data)
        return Response({"detail": "Your password has been reset. Please sign in."})


class EmailChangeConfirmView(PublicAPIView):
    throttle_scope = "email_verification"

    @extend_schema(request=s.TokenSerializer, responses=DetailSerializer)
    def post(self, request: Request) -> Response:
        serializer = s.TokenSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.confirm_email_change(serializer.validated_data["token"])
        return Response({"detail": "Email address changed."})


# --------------------------------------------------------------------- me
class MeView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    documented_delete_body = True  # DELETE takes the password (see UniversityAutoSchema)

    @property
    def throttle_scope(self) -> str | None:  # type: ignore[override]
        return "account_delete" if self.request.method == "DELETE" else None

    @extend_schema(responses=s.MeSerializer)
    def get(self, request: Request) -> Response:
        return Response(me_serializer_class()(request.user).data)

    @extend_schema(request=s.MeSerializer, responses=s.MeSerializer)
    def patch(self, request: Request) -> Response:
        serializer = me_serializer_class()(request.user, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        user = services.update_profile(request.user, serializer.validated_data)
        return Response(me_serializer_class()(user).data)

    @extend_schema(request=s.DeleteAccountSerializer, responses={204: None})
    def delete(self, request: Request) -> Response:
        serializer = s.DeleteAccountSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.delete_account(request.user, password=serializer.validated_data["password"])
        return Response(status=status.HTTP_204_NO_CONTENT)


class AvatarView(APIView):
    """Upload or remove your profile photo."""

    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [MultiPartParser]
    throttle_scope = "upload"

    @extend_schema(request={"multipart/form-data": s.AvatarUploadSerializer}, responses=s.MeSerializer)
    def post(self, request: Request) -> Response:
        serializer = s.AvatarUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = services.set_avatar(request.user, serializer.validated_data["file"])
        return Response(me_serializer_class()(user).data)

    @extend_schema(request=None, responses=s.MeSerializer)
    def delete(self, request: Request) -> Response:
        return Response(me_serializer_class()(services.remove_avatar(request.user)).data)


class PasswordChangeView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    throttle_scope = "password_change"

    @extend_schema(request=s.PasswordChangeSerializer, responses={200: s.AccessTokenSerializer, 204: None})
    def post(self, request: Request) -> Response:
        serializer = s.PasswordChangeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        session = getattr(getattr(request, "auth", None), "session", None)
        services.change_password(request.user, current_session=session, **serializer.validated_data)
        if session is None:
            return Response(status=status.HTTP_204_NO_CONTENT)
        # The old access token carries the previous security stamp; hand the
        # current session a fresh one so the caller stays signed in.
        from university.security.tokens import get_token_issuer

        access, expires = get_token_issuer().issue_access(user=request.user, session=session)
        return Response({"access": access, "access_expires_at": expires.isoformat()})


class EmailChangeView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    throttle_scope = "email_verification"

    @extend_schema(request=s.EmailChangeSerializer, responses={202: DetailSerializer})
    def post(self, request: Request) -> Response:
        serializer = s.EmailChangeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.request_email_change(request.user, **serializer.validated_data)
        return Response({"detail": GENERIC_ACCEPTED}, status=status.HTTP_202_ACCEPTED)


class PhoneView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    throttle_scope = "otp_request"

    @extend_schema(request=s.PhoneRequestSerializer, responses={202: ChallengeSerializer})
    def post(self, request: Request) -> Response:
        serializer = s.PhoneRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        challenge = services.request_phone_verification(request.user, serializer.validated_data["phone_number"])
        return Response(
            {"challenge_id": str(challenge.pk), "destination": challenge.destination_masked},
            status=status.HTTP_202_ACCEPTED,
        )

    @extend_schema(responses={204: None})
    def delete(self, request: Request) -> Response:
        services.remove_phone_number(request.user)
        return Response(status=status.HTTP_204_NO_CONTENT)


class PhoneVerifyView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    throttle_scope = "otp_verify"

    @extend_schema(request=s.PhoneConfirmSerializer, responses=s.MeSerializer)
    def post(self, request: Request) -> Response:
        serializer = s.PhoneConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = services.confirm_phone_verification(request.user, **serializer.validated_data)
        return Response(me_serializer_class()(user).data)


class _SettingsView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class: type = s.PrivacySettingsSerializer
    getter: Any = None

    def _instance(self, request: Request) -> Any:
        return type(self).getter(request.user)

    def get(self, request: Request) -> Response:
        return Response(self.serializer_class(self._instance(request)).data)

    def patch(self, request: Request) -> Response:
        instance = self._instance(request)
        serializer = self.serializer_class(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        services.update_settings(instance, serializer.validated_data)
        return Response(self.serializer_class(instance).data)


class PrivacySettingsView(_SettingsView):
    serializer_class = s.PrivacySettingsSerializer
    getter = staticmethod(services.get_privacy_settings)


class NotificationSettingsView(_SettingsView):
    serializer_class = s.NotificationSettingsSerializer
    getter = staticmethod(services.get_notification_settings)


class SecuritySettingsView(_SettingsView):
    serializer_class = s.SecuritySettingsSerializer
    getter = staticmethod(services.get_security_settings)


class ConsentView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        responses={
            200: {
                "type": "object",
                "description": "Your latest decision for each consent purpose.",
                "additionalProperties": {
                    "type": "object",
                    "properties": {
                        "granted": {"type": "boolean"},
                        "version": {"type": "string"},
                        "recorded_at": {"type": "string", "format": "date-time"},
                    },
                    "required": ["granted", "version", "recorded_at"],
                },
            }
        }
    )
    def get(self, request: Request) -> Response:
        from university.users.services.data import current_consents

        return Response(current_consents(request.user))

    @extend_schema(request=s.ConsentSerializer, responses={201: None})
    def post(self, request: Request) -> Response:
        serializer = s.ConsentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.record_consent(
            request.user,
            purpose=serializer.validated_data["purpose"],
            granted=serializer.validated_data["granted"],
            version=serializer.validated_data.get("version", ""),
            meta=ClientMeta.from_request(request),
        )
        return Response(status=status.HTTP_201_CREATED)


class DataExportView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    throttle_scope = "data_export"

    @extend_schema(responses=OpenApiTypes.OBJECT)
    def get(self, request: Request) -> Response:
        response = Response(services.export_user_data(request.user))
        response["Content-Disposition"] = 'attachment; filename="university-data-export.json"'
        return response


# ----------------------------------------------------------------- people
class UserDetailView(APIView):
    permission_classes = [permissions.AllowAny]
    throttle_scope = "profile_lookup"

    @extend_schema(responses=s.PublicProfileSerializer)
    def get(self, request: Request, user_id: Any) -> Response:
        user = selectors.get_visible_user(viewer=request.user, user_id=user_id)
        return Response(public_profile_serializer_class()(user, context={"viewer": request.user}).data)


class UserByHandleView(APIView):
    permission_classes = [permissions.AllowAny]
    throttle_scope = "profile_lookup"

    @extend_schema(responses=s.PublicProfileSerializer)
    def get(self, request: Request, handle: str) -> Response:
        user = selectors.get_visible_user(viewer=request.user, handle=handle)
        return Response(public_profile_serializer_class()(user, context={"viewer": request.user}).data)


class _UserAdminActionView(APIView):
    """Staff account actions. Authorization is enforced in the services."""

    permission_classes = [permissions.IsAuthenticated]

    def _target(self, user_id: Any) -> Any:
        user = get_user_model().all_objects.filter(pk=user_id).first()
        if user is None:
            raise NotFound("User not found.")
        return user


class SuspendUserView(_UserAdminActionView):
    @extend_schema(request=s.StatusChangeSerializer, responses={204: None})
    def post(self, request: Request, user_id: Any) -> Response:
        serializer = s.StatusChangeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.suspend_user(
            actor=request.user,
            user=self._target(user_id),
            reason=serializer.validated_data["reason"],
            until=serializer.validated_data.get("until"),
        )
        return Response(status=status.HTTP_204_NO_CONTENT)


class BanUserView(_UserAdminActionView):
    @extend_schema(request=s.StatusChangeSerializer, responses={204: None})
    def post(self, request: Request, user_id: Any) -> Response:
        serializer = s.StatusChangeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.ban_user(actor=request.user, user=self._target(user_id), reason=serializer.validated_data["reason"])
        return Response(status=status.HTTP_204_NO_CONTENT)


class ReactivateUserView(_UserAdminActionView):
    @extend_schema(request=None, responses={204: None})
    def post(self, request: Request, user_id: Any) -> Response:
        services.reactivate_user(actor=request.user, user=self._target(user_id))
        return Response(status=status.HTTP_204_NO_CONTENT)


class RestoreUserView(_UserAdminActionView):
    @extend_schema(request=None, responses={204: None})
    def post(self, request: Request, user_id: Any) -> Response:
        services.restore_user(actor=request.user, user=self._target(user_id))
        return Response(status=status.HTTP_204_NO_CONTENT)
