from __future__ import annotations

from django.db import models
from django.utils.translation import gettext_lazy as _


class OpportunityKind(models.TextChoices):
    JOB = "job", _("Job")
    INTERNSHIP = "internship", _("Internship")
    GIG = "gig", _("Gig")
    SCHOLARSHIP = "scholarship", _("Scholarship")
    FELLOWSHIP = "fellowship", _("Fellowship")
    VOLUNTEER = "volunteer", _("Volunteering")
    COMPETITION = "competition", _("Competition")


class WorkMode(models.TextChoices):
    ON_SITE = "on_site", _("On site")
    REMOTE = "remote", _("Remote")
    HYBRID = "hybrid", _("Hybrid")


class PayPeriod(models.TextChoices):
    HOUR = "hour", _("Per hour")
    DAY = "day", _("Per day")
    MONTH = "month", _("Per month")
    YEAR = "year", _("Per year")
    FIXED = "fixed", _("Fixed amount")
    STIPEND = "stipend", _("Stipend")
    UNPAID = "unpaid", _("Unpaid")


class ApplyMethod(models.TextChoices):
    IN_APP = "in_app", _("Apply on the platform")
    EXTERNAL = "external", _("Apply on the organisation's website")
    EMAIL = "email", _("Apply by email")


class OpportunityStatus(models.TextChoices):
    DRAFT = "draft", _("Draft")
    OPEN = "open", _("Open")
    CLOSED = "closed", _("Closed")


class OpportunityAudience(models.TextChoices):
    PUBLIC = "public", _("Everyone")
    INSTITUTION = "institution", _("One institution")


class ApplicationStatus(models.TextChoices):
    SUBMITTED = "submitted", _("Submitted")
    SHORTLISTED = "shortlisted", _("Shortlisted")
    REJECTED = "rejected", _("Not selected")
    HIRED = "hired", _("Selected")
    WITHDRAWN = "withdrawn", _("Withdrawn")


#: Statuses a poster may set on an application (withdrawing belongs to the applicant).
POSTER_DECISIONS = (ApplicationStatus.SHORTLISTED, ApplicationStatus.REJECTED, ApplicationStatus.HIRED)
