"""User services — every mutation of accounts goes through here.

Views stay thin: they validate input with serializers, then call one service
function. Services enforce authorization, invariants, auditing, events and
transactions.
"""

from university.users.services.account import (
    change_password,
    confirm_email_change,
    confirm_password_reset,
    remove_phone_number,
    request_email_change,
    request_password_reset,
    update_profile,
)
from university.users.services.avatars import avatar_url, remove_avatar, set_avatar
from university.users.services.data import export_user_data, record_consent
from university.users.services.lifecycle import (
    ban_user,
    delete_account,
    delete_user,
    purge_user,
    reactivate_user,
    restore_user,
    suspend_user,
)
from university.users.services.preferences import (
    ensure_user_settings,
    get_notification_settings,
    get_privacy_settings,
    get_security_settings,
    update_settings,
)
from university.users.services.registration import (
    RegistrationResult,
    create_user_from_external_identity,
    register_user,
)
from university.users.services.verification import (
    confirm_phone_verification,
    request_phone_verification,
    resend_verification_email,
    send_verification_email,
    verify_email,
)

__all__ = [
    "RegistrationResult",
    "avatar_url",
    "ban_user",
    "change_password",
    "confirm_email_change",
    "confirm_password_reset",
    "confirm_phone_verification",
    "create_user_from_external_identity",
    "delete_account",
    "delete_user",
    "ensure_user_settings",
    "export_user_data",
    "get_notification_settings",
    "get_privacy_settings",
    "get_security_settings",
    "purge_user",
    "reactivate_user",
    "record_consent",
    "register_user",
    "remove_avatar",
    "remove_phone_number",
    "request_email_change",
    "request_password_reset",
    "request_phone_verification",
    "resend_verification_email",
    "restore_user",
    "send_verification_email",
    "set_avatar",
    "suspend_user",
    "update_profile",
    "update_settings",
    "verify_email",
]
