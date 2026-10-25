from __future__ import annotations

from django.db import models
from django.utils.translation import gettext_lazy as _


class Channel(models.TextChoices):
    IN_APP = "in_app", _("In-app")
    EMAIL = "email", _("Email")
    PUSH = "push", _("Push")
    SMS = "sms", _("SMS")


#: Channels delivered outside the app (one ``Delivery`` row each).
EXTERNAL_CHANNELS = (Channel.EMAIL, Channel.PUSH, Channel.SMS)
#: Channels that interrupt people and therefore respect quiet hours.
INTERRUPTING_CHANNELS = frozenset({Channel.PUSH, Channel.SMS})


class DeliveryStatus(models.TextChoices):
    PENDING = "pending", _("Pending")
    SENDING = "sending", _("Sending")
    SENT = "sent", _("Sent")
    #: Waiting for the recipient's next email digest.
    DIGEST = "digest", _("Queued for digest")
    #: Deliberately not sent (quiet hours, hourly cap).
    SUPPRESSED = "suppressed", _("Suppressed")
    #: Not applicable (already read, no verified address, no device).
    SKIPPED = "skipped", _("Skipped")
    FAILED = "failed", _("Failed")


class Platform(models.TextChoices):
    ANDROID = "android", _("Android")
    IOS = "ios", _("iOS")
    WEB = "web", _("Web")


#: Email modes a category can use.
EMAIL_IMMEDIATE = "immediate"
EMAIL_DIGEST = "digest"
