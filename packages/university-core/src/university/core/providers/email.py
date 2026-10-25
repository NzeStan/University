"""Email provider adapters.

The default :class:`DjangoEmailProvider` delegates to Django's email backend,
which already supports SMTP and — through packages such as django-anymail —
SendGrid, Mailgun, Amazon SES, Postmark, Brevo and others. Implement
:class:`EmailProvider` to integrate anything else.

Templated messages render ``<template_prefix>_subject.txt``,
``<template_prefix>.txt`` and, when present, ``<template_prefix>.html``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template import TemplateDoesNotExist
from django.template.loader import render_to_string

from university.core.tasks import enqueue, task


@dataclass(frozen=True)
class EmailMessage:
    to: Sequence[str]
    subject: str
    body: str
    html_body: str | None = None
    from_email: str | None = None
    reply_to: Sequence[str] = field(default_factory=tuple)
    headers: Mapping[str, str] = field(default_factory=dict)


class EmailProvider(Protocol):
    def send(self, message: EmailMessage) -> None: ...


class DjangoEmailProvider:
    def send(self, message: EmailMessage) -> None:
        email = EmailMultiAlternatives(
            subject=message.subject,
            body=message.body,
            from_email=message.from_email or settings.DEFAULT_FROM_EMAIL,
            to=list(message.to),
            reply_to=list(message.reply_to) or None,
            headers=dict(message.headers) or None,
        )
        if message.html_body:
            email.attach_alternative(message.html_body, "text/html")
        email.send()


def render_email(template_prefix: str, context: Mapping[str, Any], to: Sequence[str]) -> EmailMessage:
    subject = render_to_string(f"{template_prefix}_subject.txt", dict(context)).strip()
    subject = " ".join(subject.splitlines())
    body = render_to_string(f"{template_prefix}.txt", dict(context))
    try:
        html_body: str | None = render_to_string(f"{template_prefix}.html", dict(context))
    except TemplateDoesNotExist:
        html_body = None
    return EmailMessage(to=list(to), subject=subject, body=body, html_body=html_body)


@task(name="university.core.send_templated_email")
def send_templated_email_task(template_prefix: str, context: dict[str, Any], to: list[str]) -> None:
    from university.core.providers import get_email_provider

    get_email_provider().send(render_email(template_prefix, context, to))


def send_templated_email(template_prefix: str, context: Mapping[str, Any], to: Sequence[str]) -> None:
    """Render and send an email through the task backend (after commit)."""
    enqueue(send_templated_email_task, template_prefix, dict(context), list(to))
