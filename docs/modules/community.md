# university-community

Communities with roles, privacy, invitations and delegated moderation. It depends only on
`university-core`. Communities are **audiences** and **permission scopes**, so the rest of the
platform works with them without importing this module.

```bash
pip install university-community
```

```python
INSTALLED_APPS += ["university.community"]
```

## Kinds and privacy

Kinds are configurable (`COMMUNITY.KINDS`): interest, institution, campus, department, club,
creator, study_group, other.

| Privacy | Discoverable | Joining |
| --- | --- | --- |
| `public` | yes | instant |
| `restricted` | yes | request, approved by an admin |
| `private` | no (404 to outsiders, including its member list) | invitation or invite link only |

A community can be **linked to a parent audience** (`parent_type`/`parent_id`, for example an
institution). With `requires_scope_membership`, only members of that audience can join (for
example verified students of the institution). Creating a linked community requires belonging to
that audience. Only **managers of the parent scope** can mark it `is_official`; owners can't
self-declare it.

## Posting and commenting policies

Membership decides who can *see* community content; policies decide who can *contribute*:

| Setting | Values | Applies to |
| --- | --- | --- |
| `posting_policy` | `members` (default) · `moderators` · `admins` | Top-level posts: social and anonymous |
| `commenting_policy` | `members` (default) · `moderators` · `admins` · `disabled` | Comments: social and anonymous |

For example, an announcements community with `posting_policy: "moderators"` lets everyone read and
comment while only staff post. Policies are enforced through Core's `audience.can_post` hook,
which every content module calls before accepting content into an audience. Content modules never
need to know about communities, and other audience providers (for example institutions) can
implement the same hook. A refusal returns `403 audience_posting_restricted`. Owners and admins
change policies (`community.manage`).

## Roles

`owner` (exactly one, enforced by a database constraint) > `admin` > `moderator` > `member`.

- People act only on members ranked **strictly below** them, and grant only roles strictly below
  their own.
- Ownership moves only through `transfer-ownership`; the old owner becomes an admin. Owners must
  transfer before leaving.
- Platform managers, and managers of the parent scope (role `community_manager`), outrank owners.

Each role's permissions apply **at its community's scope**, implicitly through Core's
`permissions.implicit_grants` hook (configurable in `COMMUNITY.ROLE_PERMISSIONS`):

| Role | Implicit permissions |
| --- | --- |
| owner | `community.manage`, `community.members.manage`, `events.manage`, `podcast.manage`, `moderation.cases.view/act`, `moderation.appeals.decide`, `social.content.moderate` |
| admin | `community.members.manage`, `events.manage`, `podcast.manage`, `moderation.cases.view/act`, `moderation.appeals.decide`, `social.content.moderate` |
| moderator | `moderation.cases.view/act`, `social.content.moderate` |
| member | — |

Because Core's `permissions.implicit_scopes` hook mirrors these grants, community moderators'
**moderation queues** contain exactly their community's cases.

## Platform integration

| Capability | Mechanism | Effect |
| --- | --- | --- |
| Community-only social posts | `scopes.memberships` | `visibility: "community"`, visible to active members only |
| Anonymous community boards | `scopes.memberships` | `anonymous/posts` with `visibility: "community"` |
| Delegated moderation | implicit grants and scopes | Community moderators moderate their community's content in the shared queue |
| Parent authority | the `community` scope type resolves to its parent | Institution-level managers and moderators keep authority over linked communities |
| Reporting a community | the `community.community` adapter | Reports go to the **parent scope** or the platform, never to the community's own moderators |
| Profiles | `users.public_profile` | Non-private communities, shown when `show_affiliations` is on |
| Export and purge | hooks | Purge hands ownership to the highest-ranked member, or archives the community |

## Invitations

- **Direct invitations** (`members.manage`): the invitee sees the community and accepts or
  declines. Blocks (if social is installed) make the invitee look nonexistent to the inviter.
- **Invite links**: the code is shown once and only a keyed hash is stored. Links have an expiry
  (up to `INVITE_LINK_MAX_DAYS`) and optional use limits, can be revoked, and redemption is rate
  limited.
- Banned users can't rejoin by any path until unbanned.

## API (`/api/v1/…`)

| Method & path | Who |
| --- | --- |
| `GET communities/?q=&kind=&scope_type=&scope_id=&official=` · `POST communities/` | anyone / verified users |
| `GET/PATCH/DELETE communities/{id}/` | visible / `community.manage` (DELETE archives) |
| `POST communities/{id}/official/` | parent-scope managers |
| `POST communities/{id}/join/` · `leave/` | users |
| `GET communities/{id}/members/?role=` | visible (members only for private) |
| `GET communities/{id}/requests/` · `bans/` | `community.members.manage` |
| `PATCH communities/{id}/members/{user}/` `{role}` | `members.manage` + rank |
| `POST communities/{id}/members/{user}/approve\|decline\|remove\|ban\|unban/` | `members.manage` + rank |
| `POST communities/{id}/transfer-ownership/` | owner |
| `POST communities/{id}/invitations/` · `invitations/accept\|decline/` | managers / invitee |
| `POST communities/{id}/invite-links/` · `DELETE …/invite-links/{id}/` · `POST communities/join-with-code/` | managers / users |
| `GET me/communities/` · `me/community-invitations/` | users |

## Events

`community.created|updated|archived`, `community.member.joined|requested|invited|left|removed|banned`,
`community.role.changed` and `community.ownership.transferred`. Payloads contain ids only.
