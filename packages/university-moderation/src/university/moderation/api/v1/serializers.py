"""Moderation API serializers.

Anonymity rule: for cases on anonymous content, no representation includes
the author or ``target_user`` — moderators see ``{"anonymous": true}``.
Reporter identities appear only for holders of
``moderation.reports.view_reporters``.
"""

from __future__ import annotations

from typing import Any

from rest_framework import serializers

from university.core.api.serializers import StrictModelSerializer
from university.moderation.constants import Action, RestrictionKind
from university.moderation.models import (
    ModerationAction,
    ModerationAppeal,
    ModerationCase,
    ModerationRule,
    Report,
    ReportReason,
)


def user_summary(user: Any) -> dict[str, Any] | None:
    if user is None:
        return None
    return {"id": str(user.pk), "handle": user.handle, "display_name": user.display_name}


class ReasonSerializer(StrictModelSerializer):
    class Meta:
        model = ReportReason
        fields = ("key", "label", "description", "severity", "requires_details")
        read_only_fields = fields


class ReportCreateSerializer(serializers.Serializer):
    content_type = serializers.CharField(max_length=64)
    object_id = serializers.CharField(max_length=64)
    reason = serializers.SlugField(max_length=50)
    details = serializers.CharField(max_length=1000, required=False, allow_blank=True, default="")


class MyReportSerializer(StrictModelSerializer):
    reason = serializers.SlugRelatedField(slug_field="key", read_only=True)
    content_type = serializers.CharField(source="case.content_type", read_only=True)
    object_id = serializers.CharField(source="case.object_id", read_only=True)
    outcome = serializers.SerializerMethodField()

    class Meta:
        model = Report
        fields = ("id", "content_type", "object_id", "reason", "details", "outcome", "created_at")
        read_only_fields = fields

    def get_outcome(self, obj: Report) -> str:
        """Coarse feedback: "under_review", "action_taken" or "no_action"."""
        status = obj.case.status
        return {"open": "under_review", "actioned": "action_taken"}.get(status, "no_action")


class ActionSerializer(StrictModelSerializer):
    target_user = serializers.SerializerMethodField()
    actor = serializers.SerializerMethodField()

    class Meta:
        model = ModerationAction
        fields = (
            "id",
            "action",
            "content_type",
            "object_id",
            "target_user",
            "actor",
            "automated",
            "reason",
            "explanation",
            "expires_at",
            "reversed_at",
            "reversal_reason",
            "created_at",
        )
        read_only_fields = fields

    def get_target_user(self, obj: ModerationAction) -> dict[str, Any] | None:
        if obj.case is not None and obj.case.target_is_anonymous:
            return {"anonymous": True}
        return user_summary(obj.target_user)

    def get_actor(self, obj: ModerationAction) -> dict[str, Any] | None:
        return None if obj.automated else user_summary(obj.actor)


class MyActionSerializer(StrictModelSerializer):
    """An action affecting the requesting user (no moderator identity)."""

    appeal_status = serializers.SerializerMethodField()

    class Meta:
        model = ModerationAction
        fields = (
            "id",
            "action",
            "content_type",
            "object_id",
            "reason",
            "expires_at",
            "reversed_at",
            "appeal_status",
            "created_at",
        )
        read_only_fields = fields

    def get_appeal_status(self, obj: ModerationAction) -> str | None:
        appeal = getattr(obj, "appeal", None)
        return appeal.status if appeal else None


class CaseListSerializer(StrictModelSerializer):
    author = serializers.SerializerMethodField()
    scope = serializers.SerializerMethodField()

    class Meta:
        model = ModerationCase
        fields = (
            "id",
            "content_type",
            "object_id",
            "scope",
            "status",
            "source",
            "priority",
            "report_count",
            "auto_actioned",
            "author",
            "excerpt",
            "assigned_to",
            "created_at",
            "resolved_at",
            "resolution",
        )
        read_only_fields = fields

    def get_author(self, obj: ModerationCase) -> dict[str, Any] | None:
        if obj.target_is_anonymous:
            return {"anonymous": True}
        return user_summary(obj.target_author)

    def get_scope(self, obj: ModerationCase) -> dict[str, str] | None:
        return {"type": obj.scope_type, "id": obj.scope_id} if obj.scope_type else None

    def to_representation(self, instance: ModerationCase) -> dict[str, Any]:
        data = super().to_representation(instance)
        data["assigned_to"] = user_summary(instance.assigned_to)
        return data


class CaseDetailSerializer(CaseListSerializer):
    reports = serializers.SerializerMethodField()
    actions = serializers.SerializerMethodField()
    current_status = serializers.SerializerMethodField()

    class Meta(CaseListSerializer.Meta):
        fields = (*CaseListSerializer.Meta.fields, "reports", "actions", "current_status")
        read_only_fields = fields

    def get_reports(self, obj: ModerationCase) -> list[dict[str, Any]]:
        show_reporters = self.context.get("show_reporters", False)
        rows = []
        for report in obj.reports.select_related("reason", "reporter").order_by("created_at"):
            row = {"reason": report.reason.key, "details": report.details, "created_at": report.created_at.isoformat()}
            if show_reporters:
                row["reporter"] = user_summary(report.reporter)
            rows.append(row)
        return rows

    def get_actions(self, obj: ModerationCase) -> list[dict[str, Any]]:
        return ActionSerializer(
            obj.actions.select_related("actor", "target_user", "case").order_by("created_at"), many=True
        ).data

    def get_current_status(self, obj: ModerationCase) -> str | None:
        from university.core.content import get_adapter

        try:
            ref = get_adapter(obj.content_type).resolve(obj.object_id)
        except Exception:
            return None
        return ref.status if ref else "deleted"


class CaseOpenSerializer(serializers.Serializer):
    content_type = serializers.CharField(max_length=64)
    object_id = serializers.CharField(max_length=64)
    note = serializers.CharField(max_length=500, required=False, allow_blank=True, default="")


class ActionCreateSerializer(serializers.Serializer):
    action = serializers.ChoiceField(choices=Action.choices)
    reason = serializers.CharField(max_length=500, required=False, allow_blank=True, default="")
    duration_hours = serializers.IntegerField(required=False, allow_null=True, min_value=1)
    restriction_kind = serializers.ChoiceField(choices=RestrictionKind.choices, default=RestrictionKind.POSTING)


class AppealCreateSerializer(serializers.Serializer):
    action_id = serializers.UUIDField(required=False)
    content_type = serializers.CharField(max_length=64, required=False)
    object_id = serializers.CharField(max_length=64, required=False)
    statement = serializers.CharField(max_length=2000)


class AppealSerializer(StrictModelSerializer):
    action = serializers.SerializerMethodField()
    appellant = serializers.SerializerMethodField()

    class Meta:
        model = ModerationAppeal
        fields = ("id", "action", "appellant", "statement", "status", "decided_at", "decision_reason", "created_at")
        read_only_fields = fields

    def get_action(self, obj: ModerationAppeal) -> dict[str, Any]:
        return ActionSerializer(obj.action).data

    def get_appellant(self, obj: ModerationAppeal) -> dict[str, Any] | None:
        case = obj.action.case
        if case is not None and case.target_is_anonymous:
            return {"anonymous": True}
        return user_summary(obj.appellant)


class AppealDecisionSerializer(serializers.Serializer):
    overturn = serializers.BooleanField()
    reason = serializers.CharField(max_length=500)


class RuleSerializer(StrictModelSerializer):
    class Meta:
        model = ModerationRule
        fields = ("id", "key", "name", "description", "rule_type", "params", "action", "is_active")
        read_only_fields = ("id", "key", "rule_type")

    def validate_action(self, value: str) -> str:
        from university.moderation.constants import AUTOMATABLE_ACTIONS

        if value not in AUTOMATABLE_ACTIONS:
            raise serializers.ValidationError("Automated rules may only hide content.")
        return value
