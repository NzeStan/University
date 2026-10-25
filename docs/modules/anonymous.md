# university-anonymous

Anonymous posts and comments, **unlinkable to the public and accountable to the platform**. It
requires `university-moderation` (the module refuses to run without abuse controls) and
`cryptography`.

```bash
pip install university-anonymous
```

```python
INSTALLED_APPS += ["university.moderation", "university.anonymous"]
UNIVERSITY = {"ANONYMOUS": {"IDENTITY_KEYS": [env("ANONYMOUS_IDENTITY_KEY")]}}
```

Generate a key with
`python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` and
keep it outside the database (a secret manager). Without it, the `university_anonymous.W001`
deploy check warns.

## Threat model

| Adversary | Guarantee | How |
| --- | --- | --- |
| Other users | Can't learn who wrote anything | Responses carry only `{"anonymous": true}` plus a per-thread pseudonym |
| Ordinary moderators | Can act on content without learning the author | Adapters return `author_id=None`; moderation shows `{"anonymous": true}` |
| Downstream consumers (analytics, notifications, search) | Never receive authorship | Events carry no author or actor ids |
| Someone holding a database dump | Can't link authors to items, or group one author's items | No author foreign key; per-item keyed owner tokens; randomised Fernet ciphertexts |
| Timing correlation | Hindered | Random UUIDv4 ids (even when the platform uses v7), timestamps coarsened to 5 minutes, no `updated_at` |
| "Block to unmask" attacks | Prevented | Blocks deliberately don't affect anonymous visibility; users hide individual posts instead |
| Insiders seeking a reveal | Require two people and leave a trail | Sensitive permission + justification + a different approver + expiry + audit on every retrieval |

The audit log never links a user to anonymous content. Posting and commenting aren't audited
with the author as actor, and reveal audit entries reference the request and the item, never the
identity.

## How authorship is stored

```text
AnonymousPost / AnonymousComment     ← no author column
Authorship(kind, object_id,
           owner_token     = HMAC_k1(kind:object_id:user_id)   ← proves ownership when the user asks
           identity_cipher = Fernet_k2(user_id))               ← only for audited reveals and sanctions
```

- **Ownership checks** (is this my post? may I delete it? may I appeal?) recompute the token for the
  requesting user. Nothing is looked up by user.
- **Export and purge** scan authorship records and test each token, because no author index exists
  to look up. This costs one HMAC per item and runs only on rare, throttled operations.
- **Key rotation**: list the new key first in `IDENTITY_KEYS` (old keys still decrypt). HMAC keys
  rotate through `SECURITY.HMAC_KEY_FALLBACKS`.

## Abuse controls

- Posts are restricted to audiences (`institution`, `campus`, `community`). Public anonymous posts
  are opt-in (`ALLOWED_VISIBILITIES`).
- Posting requires a **verified email** and a **minimum account age** (24 hours by default), and
  membership of the target audience.
- Rate limits: `anonymous_post` 5/hour plus `anonymous_post_daily` 20/day; `anonymous_comment`
  30/hour; reactions; and `anonymous_reveal` 10/day.
- Content goes through the anti-spam provider. *Review* holds it as `pending_review`, visible to the
  author only.
- Reports, hide/remove and appeals go through `university-moderation`. Sanctions on authors (for
  example a 72-hour restriction) need `anonymous.authors.sanction` and are enforced through Core's
  `content.can_create` hook, without revealing the author to the moderator.

## Pseudonyms

Each commenter gets a stable alias within a thread ("Quiet Heron"); the post's author is shown as
`OP` (`SHOW_OP_LABEL`). Aliases come from `HMAC(post_id:user_id)`, so one user's aliases differ
across threads, and collisions inside a thread get a numeric suffix. Comments are ordered by a
per-thread position, because coarsened timestamps can't order them.

## Identity reveal (two-person rule)

```http
POST /api/v1/anonymous/reveal-requests/            {"kind": "post", "object_id": "…",
                                                    "justification": "Court order …", "case_reference": "…"}
POST /api/v1/anonymous/reveal-requests/{id}/decide/ {"approve": true, "reason": "Valid order"}   # a different person
GET  /api/v1/anonymous/reveal-requests/{id}/identity/                                          # requester only, before expiry
```

| Permission | Holder |
| --- | --- |
| `anonymous.identity.reveal` | Requests and retrieves (for example a legal or safety officer) |
| `anonymous.identity.reveal_approve` | Approves (for example the data-protection officer); can never approve their own request (also enforced by a DB constraint) |
| `anonymous.authors.sanction` | Applies account sanctions to anonymous authors through moderation |

Justifications need at least `REVEAL_MIN_JUSTIFICATION` characters, approvals expire after
`REVEAL_APPROVAL_TTL_HOURS`, the identity response is `Cache-Control: no-store`, and every request,
decision and retrieval is audited. The reveal path, authorship records and reveal requests are
deliberately **not** in the Django admin.

## API (`/api/v1/anonymous/…`)

| Method & path | Description |
| --- | --- |
| `GET/POST posts/?audience_type=&audience_id=` | Feed of your audiences / create (`body`, `visibility`, `audience_id`) |
| `GET/DELETE posts/{id}/` | Read / delete your own |
| `GET/POST posts/{id}/comments/` | Thread / comment |
| `DELETE comments/{id}/` | Delete your own comment |
| `POST/DELETE posts/{id}/reaction/` | React |
| `POST/DELETE posts/{id}/hide/` | Hide a post from your own feed |
| `GET/POST reveal-requests/` · `POST …/decide/` · `GET …/identity/` | Reveal workflow |

Reports and appeals use the moderation API with `content_type` set to `anonymous.post` or
`anonymous.comment`.

## Verification

`tests/test_leakage.py` is the mandatory leakage suite. It probes API responses for every kind of
viewer (including moderators and superusers), moderation views, events, raw database rows, the
audit log, errors, exports, ids and timestamps, and the block oracle. It was mutation-tested:
deliberately leaking the author in responses or events makes it fail.

## Known limits (deployment responsibilities)

- Web-server access logs record IP, path and time. Correlating them with posting time can
  deanonymise. Keep access-log retention short and restricted.
- Someone holding the database **and** the HMAC and identity keys can recover authorship. That is
  the intended accountability path, so protect those keys accordingly.
- Writing style (stylometry) is outside what a backend can prevent.
