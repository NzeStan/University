# university-moderation

Reports, moderation cases, actions, appeals and explainable automated rules for **any** content
type. It depends only on `university-core`. Content modules describe their content through Core
**content adapters**, so moderation never imports them and they never import moderation.

```bash
pip install university-moderation
```

```python
INSTALLED_APPS += ["university.moderation"]
```

## How content becomes moderatable

A content module contributes adapters from its AppConfig:

```python
class SocialConfig(UniversityAppConfig):
    def get_content_adapters(self):
        return [SocialPostAdapter(), SocialCommentAdapter()]
```

An adapter (`university.core.content.ContentAdapter`) implements `resolve` (returning a
moderator-safe `ContentRef`) and `can_view`. Registering one does **not** make content
reportable: many adapters exist only so other modules can name things (for example
`institution.institution`, used in notifications).

To take part in moderation, an adapter sets **`moderatable = True`** and implements `hide`,
`restore` and `remove`. It can optionally implement `is_author`, `resolve_author` and
`sanction_permission`. Opting in is a policy decision. `ContentRef.scope` decides who
investigates, because cases route to that scope's moderators. The implemented state changes
decide which actions apply. Core's system check `university.E003` rejects a moderatable adapter
that doesn't implement them. Reports, moderator-opened cases and new actions resolve adapters
with `get_moderatable_adapter()`, so a display-only type is indistinguishable from an unknown one
(`404 Unknown content type.`). Reversals and appeals of existing actions keep working regardless.

| Moderatable | Display only |
| --- | --- |
| `social.post`, `social.comment`, `anonymous.post`, `anonymous.comment`, `community.community`, `users.user` (accounts, provided by moderation) | `institution.institution` |

Content modules call `university.core.content.ensure_can_create(user, "social.post")` before
accepting content. Moderation answers the `content.can_create` hook, so a restriction applies in
every module at once.

## Flow

```text
report ─► case (one open case per item; priority = max severity × 10 + report count)
            │  automated rules may hide the content (reversible, explained, case stays open)
            ▼
moderator queue (scoped) ─► action: dismiss · warn · hide · remove · restore · restrict · suspend · ban
            │
            ▼
affected user ─► appeal ─► decided by a different moderator ─► overturned (action reversed) / upheld
```

- **Reporting**: users can only report content they can see, and can't report their own. One
  report per user per case. Reasons are configurable (and seeded): spam, harassment, hate speech,
  violence, child safety, self-harm, privacy violation, impersonation, misinformation, academic
  dishonesty, illegal activity, other. The reporter is never revealed to the reported user.
  Reporters get coarse feedback (`under_review`, `action_taken`, `no_action`).
- **Evidence**: each case keeps a text snapshot from when it opened, so editing or deleting the
  content doesn't destroy evidence. Snapshots are purged with the case and erased when the author's
  account is purged.

## Scoped authority

Each case stores its content's audience scope and **all ancestor scopes** (`CaseScope`).
Moderators see and act only where they hold permissions:

| Permission | Purpose |
| --- | --- |
| `moderation.cases.view` / `moderation.cases.act` | Queue and actions (grantable at any scope) |
| `moderation.appeals.decide` | Decide appeals (any scope) |
| `moderation.users.restrict` | Time-boxed content-creation restrictions (platform) |
| `moderation.reports.view_reporters` | See who reported (sensitive; viewing is audited) |
| `moderation.rules.manage` | Edit automated rules |

`suspend` and `ban` also require Core's `users.suspend` and `users.ban`. User-level actions on
anonymous content also require the adapter's `sanction_permission` (see below).

Roles: `platform_moderator`, `scoped_moderator` (assign at an institution, campus or community
scope) and `trust_safety_lead` (everything, including account sanctions).

**Conflict of interest**: moderators can't act on their own content (`409 conflict_of_interest`).
**Four-eyes appeals**: the moderator who took an action can't decide its appeal.

## Automated rules

Seeded from `MODERATION.DEFAULT_RULES` and editable by `moderation.rules.manage`:

| Rule type | Default | Effect |
| --- | --- | --- |
| `report_threshold` | 5 reports | hide |
| `severity` | a `critical` reason | hide |

Rules can only take **reversible content actions** (hide). Each rule fires at most once per case,
records a machine-readable explanation (`{"rule", "rule_type", "inputs"}`) and leaves the case open
for a human decision.

## Anonymous content

For content whose adapter reports `is_anonymous`:

- the case stores **no author**. Queues, case details, actions, appeals and events show
  `{"anonymous": true}`;
- content actions (hide, remove, restore) work normally;
- user-level sanctions (warn, restrict, suspend, ban) additionally require the adapter's
  `sanction_permission` (`anonymous.authors.sanction`). The resulting action record does link the
  user to the item, which is unavoidable when sanctioning someone. Each such use is audited as
  `anonymous.identity.used_for_sanction`, and the user is still never shown in responses;
- the author can appeal by proving authorship (through the adapter's owner token) without being
  identified to reviewers.

## API (`/api/v1/moderation/…`)

| Method & path | Who |
| --- | --- |
| `GET reasons/` | anyone |
| `POST reports/` · `GET me/reports/` | users |
| `GET me/actions/` · `POST appeals/` (`action_id`, or `content_type` + `object_id`) · `GET me/appeals/` | affected users |
| `GET cases/?status=&content_type=&scope_type=&scope_id=&assigned=me` · `POST cases/` | moderators (scoped) |
| `GET cases/{id}/` · `POST cases/{id}/assign/` · `POST cases/{id}/actions/` | moderators (scoped) |
| `GET appeal-queue/` · `POST appeals/{id}/decide/` | appeal deciders (scoped) |
| `POST restrictions/{id}/lift/` | `moderation.users.restrict` |
| `GET rules/` · `PATCH rules/{id}/` | `moderation.rules.manage` |

## Events

`moderation.report.created`, `moderation.case.opened`, `moderation.action.taken`,
`moderation.action.reversed`, `moderation.appeal.filed` and `moderation.appeal.decided`. Payloads
carry ids. `target_user_id` is omitted for anonymous content.

## Privacy and retention

Data export lists reports made, actions received, restrictions and appeals. Purge deletes the
user's reports and erases evidence snapshots of their content; action records stay for
accountability. Resolved cases (with their reports and snapshots) are deleted after
`RESOLVED_CASE_RETENTION_DAYS` (730); actions are kept.
