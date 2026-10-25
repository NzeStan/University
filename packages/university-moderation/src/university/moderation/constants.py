from __future__ import annotations

from django.db import models
from django.utils.translation import gettext_lazy as _


class Severity(models.TextChoices):
    LOW = "low", _("Low")
    MEDIUM = "medium", _("Medium")
    HIGH = "high", _("High")
    CRITICAL = "critical", _("Critical")


class CaseStatus(models.TextChoices):
    OPEN = "open", _("Open")
    ACTIONED = "actioned", _("Actioned")
    DISMISSED = "dismissed", _("Dismissed")


class CaseSource(models.TextChoices):
    REPORT = "report", _("User report")
    MANUAL = "manual", _("Opened by a moderator")


class Action(models.TextChoices):
    DISMISS = "dismiss", _("Dismiss")
    WARN = "warn", _("Warn the author")
    HIDE = "hide", _("Hide content")
    REMOVE = "remove", _("Remove content")
    RESTORE = "restore", _("Restore content")
    RESTRICT = "restrict", _("Restrict the author")
    SUSPEND = "suspend", _("Suspend the author")
    BAN = "ban", _("Ban the author")


CONTENT_ACTIONS = frozenset({Action.HIDE, Action.REMOVE, Action.RESTORE})
USER_ACTIONS = frozenset({Action.WARN, Action.RESTRICT, Action.SUSPEND, Action.BAN})
APPEALABLE_ACTIONS = frozenset({Action.WARN, Action.HIDE, Action.REMOVE, Action.RESTRICT, Action.SUSPEND, Action.BAN})
#: Actions automated rules may take (reversible, content-level only).
AUTOMATABLE_ACTIONS = frozenset({Action.HIDE})


class RestrictionKind(models.TextChoices):
    POSTING = "posting", _("Cannot create posts")
    COMMENTING = "commenting", _("Cannot comment")
    ALL = "all", _("Cannot create any content")


class AppealStatus(models.TextChoices):
    PENDING = "pending", _("Pending")
    UPHELD = "upheld", _("Upheld (action stands)")
    OVERTURNED = "overturned", _("Overturned")


class RuleType(models.TextChoices):
    REPORT_THRESHOLD = "report_threshold", _("Report count threshold")
    SEVERITY = "severity", _("Report reason severity")
