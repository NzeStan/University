"""university-moderation: reports, cases, actions, rules, appeals, anonymity."""

from __future__ import annotations

import datetime as dt

import pytest
from django.test import override_settings
from django.utils import timezone

from tests.notes.models import Note
from university.audit.models import AuditLog
from university.core.content import can_create_content
from university.core.events import event_bus
from university.core.testing import create_user
from university.moderation.models import ModerationAction, ModerationCase, ModerationRule, Report, UserRestriction
from university.permissions.models import Role
from university.permissions.scopes import Scope
from university.permissions.services import assign_role
from university.users.constants import UserStatus

pytestmark = pytest.mark.django_db
BASE = "/api/v1/moderation"


def report(client, obj, reason="harassment", content_type="notes.note", **extra):
    return client.post(
        f"{BASE}/reports/",
        {"content_type": content_type, "object_id": str(obj.pk), "reason": reason, **extra},
        format="json",
    )


def act(client, case_id, action, **extra):
    return client.post(
        f"{BASE}/cases/{case_id}/actions/", {"action": action, "reason": "policy", **extra}, format="json"
    )


# ------------------------------------------------------------------ reports
def test_reasons_are_seeded(api_client):
    keys = {r["key"] for r in api_client.get(f"{BASE}/reasons/").json()}
    assert {"spam", "harassment", "self_harm", "academic_dishonesty", "other"} <= keys


def test_reporting_creates_one_case_per_item(auth_client, other_user, note, third_party):
    first = report(auth_client(other_user), note)
    assert first.status_code == 201 and first.json()["outcome"] == "under_review"
    assert report(auth_client(other_user), note).status_code == 409  # once per reporter
    assert report(auth_client(third_party), note, reason="spam").status_code == 201
    case = ModerationCase.objects.get()
    assert case.report_count == 2 and case.target_author_id == note.author_id
    assert case.priority == 4 * 10 + 2  # max severity weight (high=4) * 10 + reports


def test_report_validation(auth_client, user, other_user, note):
    client = auth_client(other_user)
    assert report(client, note, reason="nonsense").status_code == 400
    assert report(client, note, reason="other").status_code == 400  # details required
    assert report(client, note, reason="other", details="It's a scam link").status_code == 201
    assert report(auth_client(user), note).json()["error"]["code"] == "self_report"
    assert (
        client.post(
            f"{BASE}/reports/", {"content_type": "nope.x", "object_id": str(note.pk), "reason": "spam"}, format="json"
        ).status_code
        == 404
    )


@pytest.mark.security
def test_cannot_report_invisible_content(auth_client, other_user, note):
    Note.objects.filter(pk=note.pk).update(removed=True)
    assert report(auth_client(other_user), note).status_code == 404


def test_report_rate_limit(auth_client, other_user, user):
    notes = [Note.objects.create(author=user, body=f"n{i}") for i in range(3)]
    with override_settings(UNIVERSITY={"THROTTLE_RATES": {"report": "2/hour"}}):
        client = auth_client(other_user)
        assert report(client, notes[0]).status_code == 201
        assert report(client, notes[1]).status_code == 201
        assert report(client, notes[2]).status_code == 429


def test_my_reports_outcome(auth_client, other_user, moderator, note):
    report(auth_client(other_user), note)
    case = ModerationCase.objects.get()
    act(auth_client(moderator), case.pk, "hide")
    mine = auth_client(other_user).get(f"{BASE}/me/reports/").json()["results"]
    assert mine[0]["outcome"] == "action_taken"


# ---------------------------------------------------------------- queues
def test_queue_requires_permission_and_is_scoped(auth_client, user, other_user, moderator, third_party):
    scoped_note = Note.objects.create(author=user, body="x", scope_type="institution", scope_id="i-1")
    other_scope = Note.objects.create(author=user, body="y", scope_type="institution", scope_id="i-2")
    report(auth_client(other_user), scoped_note)
    report(auth_client(other_user), other_scope)
    assert auth_client(third_party).get(f"{BASE}/cases/").json()["results"] == []
    assign_role(user=third_party, role_key="scoped_moderator", scope=Scope("institution", "i-1"))
    visible = auth_client(third_party).get(f"{BASE}/cases/").json()["results"]
    assert [c["object_id"] for c in visible] == [str(scoped_note.pk)]
    other_case = ModerationCase.objects.get(object_id=str(other_scope.pk))
    assert auth_client(third_party).get(f"{BASE}/cases/{other_case.pk}/").status_code == 403
    assert act(auth_client(third_party), other_case.pk, "hide").status_code == 403
    assert len(auth_client(moderator).get(f"{BASE}/cases/").json()["results"]) == 2


def test_queue_ordered_by_priority(auth_client, user, other_user, moderator):
    spam = Note.objects.create(author=user, body="spam")
    threat = Note.objects.create(author=user, body="threat")
    report(auth_client(other_user), spam, reason="spam")
    report(auth_client(other_user), threat, reason="violence")
    order = [c["object_id"] for c in auth_client(moderator).get(f"{BASE}/cases/").json()["results"]]
    assert order[0] == str(threat.pk)


def test_reporters_hidden_unless_permitted(auth_client, other_user, moderator, note):
    report(auth_client(other_user), note)
    case = ModerationCase.objects.get()
    detail = auth_client(moderator).get(f"{BASE}/cases/{case.pk}/").json()
    assert "reporter" not in detail["reports"][0]
    lead = create_user("lead@example.com", handle="tslead")
    assign_role(user=lead, role_key="trust_safety_lead")
    detail = auth_client(lead).get(f"{BASE}/cases/{case.pk}/").json()
    assert detail["reports"][0]["reporter"]["handle"] == "grace"
    assert AuditLog.objects.filter(action="moderation.reporters.viewed").exists()


# ---------------------------------------------------------------- actions
def test_hide_remove_restore(auth_client, other_user, moderator, note):
    report(auth_client(other_user), note)
    case = ModerationCase.objects.get()
    response = act(auth_client(moderator), case.pk, "hide")
    assert response.status_code == 201
    note.refresh_from_db()
    assert note.hidden
    case.refresh_from_db()
    assert case.status == "actioned" and case.resolution == "hide"
    act(auth_client(moderator), case.pk, "restore")
    note.refresh_from_db()
    assert not note.hidden
    act(auth_client(moderator), case.pk, "remove")
    note.refresh_from_db()
    assert note.removed
    assert AuditLog.objects.filter(action="moderation.action.remove", actor=moderator).exists()


def test_non_moderators_cannot_act(auth_client, other_user, third_party, note):
    report(auth_client(other_user), note)
    case = ModerationCase.objects.get()
    assert act(auth_client(third_party), case.pk, "dismiss").status_code == 403
    assert auth_client(third_party).get(f"{BASE}/cases/{case.pk}/").status_code == 403


def test_restriction_enforced_across_modules(auth_client, user, other_user, moderator, note):
    report(auth_client(other_user), note)
    case = ModerationCase.objects.get()
    assert act(auth_client(moderator), case.pk, "restrict").status_code == 400  # duration required
    assert (
        act(auth_client(moderator), case.pk, "restrict", duration_hours=48, restriction_kind="posting").status_code
        == 201
    )
    assert not can_create_content(user, "social.post")
    assert not can_create_content(user, "anonymous.post")
    assert can_create_content(user, "social.comment")
    restriction = UserRestriction.objects.get()
    assert auth_client(moderator).post(f"{BASE}/restrictions/{restriction.pk}/lift/").status_code == 204
    assert can_create_content(user, "social.post")


def test_restriction_requires_restrict_permission(auth_client, other_user, third_party, note):
    report(auth_client(other_user), note)
    assign_role(user=third_party, role_key="scoped_moderator", scope=Scope("institution", "x"))
    Role.objects.create(key="act_everywhere", name="x", permissions=["moderation.cases.act", "moderation.cases.view"])
    assign_role(user=third_party, role_key="act_everywhere")
    case = ModerationCase.objects.get()
    assert act(auth_client(third_party), case.pk, "restrict", duration_hours=1).status_code == 403


def test_suspend_and_ban_need_account_permissions(auth_client, user, other_user, moderator, note):
    report(auth_client(other_user), note)
    case = ModerationCase.objects.get()
    assert act(auth_client(moderator), case.pk, "suspend", duration_hours=24).status_code == 403
    lead = create_user("lead@example.com", handle="tslead")
    assign_role(user=lead, role_key="trust_safety_lead")
    assert act(auth_client(lead), case.pk, "suspend", duration_hours=24).status_code == 201
    user.refresh_from_db()
    assert user.status == UserStatus.SUSPENDED


def test_warn_records_action_for_the_author(auth_client, user, other_user, moderator, note):
    report(auth_client(other_user), note)
    act(auth_client(moderator), ModerationCase.objects.get().pk, "warn")
    mine = auth_client(user).get(f"{BASE}/me/actions/").json()["results"]
    assert mine[0]["action"] == "warn" and "actor" not in mine[0]


@pytest.mark.security
def test_conflict_of_interest(auth_client, moderator, other_user):
    own = Note.objects.create(author=moderator, body="mod's own")
    report(auth_client(other_user), own)
    case = ModerationCase.objects.get()
    response = act(auth_client(moderator), case.pk, "dismiss")
    assert response.status_code == 403 and response.json()["error"]["code"] == "conflict_of_interest"


def test_dismiss_and_manual_case(auth_client, moderator, user):
    note = Note.objects.create(author=user, body="borderline")
    opened = auth_client(moderator).post(
        f"{BASE}/cases/", {"content_type": "notes.note", "object_id": str(note.pk), "note": "proactive"}, format="json"
    )
    assert opened.status_code == 201 and opened.json()["source"] == "manual"
    assert act(auth_client(moderator), opened.json()["id"], "dismiss").json()["action"] == "dismiss"
    assert ModerationCase.objects.get().status == "dismissed"


def test_account_reports(auth_client, user, other_user, moderator):
    response = report(auth_client(other_user), user, content_type="users.user", reason="impersonation")
    assert response.status_code == 201
    case = ModerationCase.objects.get()
    assert act(auth_client(moderator), case.pk, "hide").status_code == 400  # not supported for accounts
    assert act(auth_client(moderator), case.pk, "warn").status_code == 201


# ------------------------------------------------------------------ rules
def test_report_threshold_rule_hides_but_leaves_case_open(auth_client, user, note):
    ModerationRule.objects.filter(key="report_threshold").update(params={"threshold": 3})
    for i in range(3):
        reporter = create_user(f"r{i}@example.com", handle=f"reporter{i}")
        report(auth_client(reporter), note, reason="spam")
    note.refresh_from_db()
    case = ModerationCase.objects.get()
    assert note.hidden and case.status == "open" and case.auto_actioned
    action = ModerationAction.objects.get(automated=True)
    assert action.explanation == {
        "rule": "report_threshold",
        "rule_type": "report_threshold",
        "inputs": {"report_count": 3, "threshold": 3},
    }
    assert action.actor is None


def test_critical_reason_rule_fires_once(auth_client, other_user, third_party, note):
    report(auth_client(other_user), note, reason="violence")
    report(auth_client(third_party), note, reason="violence")
    assert ModerationAction.objects.filter(automated=True, rule__key="critical_report").count() == 1


def test_rules_can_only_hide(auth_client, moderator):
    lead = create_user("lead@example.com", handle="tslead")
    assign_role(user=lead, role_key="trust_safety_lead")
    rule = ModerationRule.objects.get(key="report_threshold")
    assert auth_client(moderator).get(f"{BASE}/rules/").status_code == 403
    assert auth_client(lead).patch(f"{BASE}/rules/{rule.pk}/", {"action": "remove"}, format="json").status_code == 400
    assert auth_client(lead).patch(f"{BASE}/rules/{rule.pk}/", {"is_active": False}, format="json").status_code == 200


# ---------------------------------------------------------------- appeals
def _hidden_case(auth_client, other_user, moderator, note):
    report(auth_client(other_user), note)
    case = ModerationCase.objects.get()
    action_id = act(auth_client(moderator), case.pk, "hide").json()["id"]
    return case, action_id


def test_appeal_overturned_by_different_moderator(auth_client, user, other_user, moderator, second_moderator, note):
    _, action_id = _hidden_case(auth_client, other_user, moderator, note)
    filed = auth_client(user).post(
        f"{BASE}/appeals/", {"action_id": action_id, "statement": "This was satire, not harassment."}, format="json"
    )
    assert filed.status_code == 201
    assert (
        auth_client(user)
        .post(f"{BASE}/appeals/", {"action_id": action_id, "statement": "again please"}, format="json")
        .status_code
        == 409
    )
    appeal_id = filed.json()["id"]
    four_eyes = auth_client(moderator).post(
        f"{BASE}/appeals/{appeal_id}/decide/", {"overturn": True, "reason": "ok"}, format="json"
    )
    assert four_eyes.status_code == 403 and four_eyes.json()["error"]["code"] == "four_eyes_required"
    queue = auth_client(second_moderator).get(f"{BASE}/appeal-queue/").json()["results"]
    assert queue[0]["id"] == appeal_id
    decided = auth_client(second_moderator).post(
        f"{BASE}/appeals/{appeal_id}/decide/", {"overturn": True, "reason": "Satire"}, format="json"
    )
    assert decided.json()["status"] == "overturned"
    note.refresh_from_db()
    assert not note.hidden
    assert ModerationAction.objects.get(pk=action_id).reversed_at is not None
    assert auth_client(user).get(f"{BASE}/me/appeals/").json()[0]["status"] == "overturned"


@pytest.mark.security
def test_only_the_affected_user_can_appeal(auth_client, user, other_user, third_party, moderator, note):
    _, action_id = _hidden_case(auth_client, other_user, moderator, note)
    for stranger in (other_user, third_party):
        response = auth_client(stranger).post(
            f"{BASE}/appeals/", {"action_id": action_id, "statement": "Let me appeal it"}, format="json"
        )
        assert response.status_code == 404


def test_appeal_window(auth_client, user, other_user, moderator, note):
    _, action_id = _hidden_case(auth_client, other_user, moderator, note)
    ModerationAction.objects.filter(pk=action_id).update(created_at=timezone.now() - dt.timedelta(days=30))
    response = auth_client(user).post(
        f"{BASE}/appeals/", {"action_id": action_id, "statement": "Too late appeal"}, format="json"
    )
    assert response.json()["error"]["code"] == "appeal_window_closed"


def test_appeal_by_content_reference_and_upheld(auth_client, user, other_user, moderator, second_moderator, note):
    _hidden_case(auth_client, other_user, moderator, note)
    filed = auth_client(user).post(
        f"{BASE}/appeals/",
        {"content_type": "notes.note", "object_id": str(note.pk), "statement": "Please reconsider"},
        format="json",
    )
    assert filed.status_code == 201
    decided = auth_client(second_moderator).post(
        f"{BASE}/appeals/{filed.json()['id']}/decide/", {"overturn": False, "reason": "Clear violation"}, format="json"
    )
    assert decided.json()["status"] == "upheld"
    note.refresh_from_db()
    assert note.hidden


# --------------------------------------------------------------- anonymity
@pytest.mark.security
def test_anonymous_content_never_exposes_author(auth_client, user, other_user, moderator, anon_note):
    seen = []
    event_bus.subscribe("moderation.*", seen.append)
    try:
        report(auth_client(other_user), anon_note, content_type="notes.anonymous_note")
        case = ModerationCase.objects.get()
        assert case.target_author is None and case.target_is_anonymous
        detail = auth_client(moderator).get(f"{BASE}/cases/{case.pk}/")
        listing = auth_client(moderator).get(f"{BASE}/cases/")
        action = act(auth_client(moderator), case.pk, "hide")
    finally:
        event_bus.unsubscribe("moderation.*", seen.append)
    author_id = str(user.pk)
    for response in (detail, listing, action):
        assert author_id not in response.content.decode()
    assert detail.json()["author"] == {"anonymous": True}
    assert ModerationAction.objects.get().target_user is None
    assert all("target_user_id" not in e.payload and author_id not in str(e.payload) for e in seen)


@pytest.mark.security
def test_sanctioning_anonymous_authors_requires_extra_permission(auth_client, user, other_user, moderator, anon_note):
    report(auth_client(other_user), anon_note, content_type="notes.anonymous_note")
    case = ModerationCase.objects.get()
    assert act(auth_client(moderator), case.pk, "warn").status_code == 403
    Role.objects.create(key="anon_sanctioner", name="x", permissions=["notes.authors.sanction"])
    assign_role(user=moderator, role_key="anon_sanctioner")
    response = act(auth_client(moderator), case.pk, "warn")
    assert response.status_code == 201
    assert response.json()["target_user"] == {"anonymous": True}  # never in responses
    assert AuditLog.objects.filter(action="anonymous.identity.used_for_sanction", actor=moderator).exists()


@pytest.mark.security
def test_anonymous_author_can_appeal_without_being_identified(
    auth_client, user, other_user, moderator, second_moderator, anon_note
):
    report(auth_client(other_user), anon_note, content_type="notes.anonymous_note")
    case = ModerationCase.objects.get()
    act(auth_client(moderator), case.pk, "hide")
    payload = {
        "content_type": "notes.anonymous_note",
        "object_id": str(anon_note.pk),
        "statement": "This is not abuse.",
    }
    assert auth_client(other_user).post(f"{BASE}/appeals/", payload, format="json").status_code == 404
    assert auth_client(user).post(f"{BASE}/appeals/", payload, format="json").status_code == 201
    queue = auth_client(second_moderator).get(f"{BASE}/appeal-queue/")
    assert queue.json()["results"][0]["appellant"] == {"anonymous": True}
    assert str(user.pk) not in queue.content.decode()


def test_export_and_purge(auth_client, user, other_user, moderator, note):
    from university.core.testing import PASSWORD
    from university.users.services import delete_account, purge_user

    report(auth_client(user), Note.objects.create(author=other_user, body="theirs"))
    report(auth_client(other_user), note)
    act(auth_client(moderator), ModerationCase.objects.get(object_id=str(note.pk)).pk, "warn")
    data = auth_client(user).get("/api/v1/me/export/").json()["moderation"]
    assert data["reports_made"] and data["actions_received"][0]["action"] == "warn"
    delete_account(user, password=PASSWORD)
    purge_user(type(user).all_objects.get(pk=user.pk))
    assert not Report.objects.filter(reporter=user).exists()
    assert ModerationCase.objects.get(object_id=str(note.pk)).excerpt == ""
    assert ModerationAction.objects.filter(action="warn").exists()  # accountability kept
