# university-institution

Institutions, campuses, academic structure and **verified** memberships. It doesn't assume any
country or institution: types, unit types, roles, qualification levels and verification methods
are all configuration or data.

```bash
pip install university-institution
```

```python
INSTALLED_APPS += ["university.institution"]
```

```bash
python manage.py migrate
python manage.py university_import_institutions institutions.json   # optional seed data
```

## Data model

```text
InstitutionType (configurable)
Institution ──┬── InstitutionDomain   email domains used for verification
              ├── Campus               one main campus (DB constraint)
              ├── AcademicUnit tree    college/faculty/school/department/… (+ proxy models)
              ├── Programme ── Level   e.g. B.Sc. Computer Science → 100 Level / ND1 / HND2
              ├── AcademicSession ── Semester   one current per institution/session (DB constraint)
              └── InstitutionMembership ── VerificationRequest
```

- An **institution is a permission scope** (`Scope("institution", id)`), and a campus scope
  resolves to its institution. Institution administrators therefore manage only their own
  institution, and that includes its campuses.
- A user may belong to **several institutions** (configurable), with one open membership per
  `(user, institution, role)` and an optional primary membership.
- **Student/staff numbers are never stored in plaintext**: only an HMAC (one open membership per
  identifier, per role, per institution) and a masked hint such as `*****042`.

## Membership lifecycle

```text
request ─► pending ─► start verification (method) ─► awaiting_user ─► complete ─┐
              │                         └─────────► pending_review ─► approve ─┼─► verified
              └─────────────────────────────────────────────────────► reject ──┘   │
                                                       suspended ◄─ suspend ◄──────┤
                                                       revoked   ◄─ revoke  ◄──────┤
                                                       left      ◄─ leave   ◄──────┘
```

Roles listed in `AUTO_VERIFY_ROLES` (default `guest`) are verified on joining.

## Verification providers

| Key | Proof | Reviewer needed |
| --- | --- | --- |
| `institution_email` | One-time code sent to an address on one of the institution's **verified** domains; each address can verify only one account | No |
| `student_id` | Student/staff number, stored as a hash | Yes |
| `document` | Uploaded ID or admission letter; content-validated and kept in private storage; deleted after the retention period | Yes |
| `manual` | Optional note | Yes |
| `AutoApproveProvider` | None (development only; not enabled by default) | No |

Each institution chooses its methods (`verification_methods`). Otherwise
`DEFAULT_VERIFICATION_METHODS` applies.

To add a provider (for example a registry lookup or an institution's SSO):

```python
from university.institution.verification import VerificationProvider


class CampusSSOProvider(VerificationProvider):
    label = "Campus single sign-on"

    def start(self, *, membership, data, file=None):
        claims = verify_campus_sso_token(data["token"], institution=membership.institution)
        return self.create_request(membership, approved=claims is not None, evidence={"source": "sso"})


UNIVERSITY = {
    "INSTITUTION": {
        "VERIFICATION_PROVIDERS": {
            **DEFAULTS["VERIFICATION_PROVIDERS"],
            "campus_sso": "myproject.verification.CampusSSOProvider",
        }
    }
}
```

Providers never change membership status themselves. The service approves based on the request
status the provider returns (`approved`, `awaiting_user` or `pending_review`).

## Permissions and roles

| Permission | Scopes | Purpose |
| --- | --- | --- |
| `institution.manage` | platform | Create institutions; change status or verification; verify domains |
| `institution.edit` | platform, institution | Edit the profile |
| `institution.structure.manage` | platform, institution | Campuses, units, programmes, levels, sessions |
| `institution.domains.manage` | platform, institution | Email domains (only platform managers can mark them verified) |
| `institution.memberships.view` | platform, institution | List members |
| `institution.memberships.verify` | platform, institution | Approve/reject; view documents (sensitive) |
| `institution.memberships.manage` | platform, institution | Suspend/revoke |

System roles: `institution_admin` and `institution_verifier` (institution scope), and
`institution_platform_manager` (platform). Grant them through `/api/v1/role-assignments/`.
Admins can delegate within their institution but can never escalate beyond it.

## API

| Method & path | Access |
| --- | --- |
| `GET /institution-types/` | public |
| `GET /institutions/?country=&type=&q=&verified=` · `POST` | public · `institution.manage` |
| `GET/PATCH /institutions/{id}/` | public · `institution.edit` (platform fields need `institution.manage`) |
| `GET/POST /institutions/{id}/domains/` · `DELETE …/domains/{id}/` | public (verified only) · `institution.domains.manage` |
| `GET/POST /institutions/{id}/campuses/` · `units/?type=&parent=` · `programmes/` · `levels/` · `sessions/` | public · `institution.structure.manage` |
| `GET/PATCH /institutions/{id}/{campuses\|units\|programmes\|levels\|sessions}/{id}/` | public · `institution.structure.manage` |
| `POST /institutions/{id}/sessions/{id}/semesters/` | `institution.structure.manage` |
| `GET /institutions/{id}/memberships/?status=&role=` | `institution.memberships.view` |
| `POST /institutions/{id}/memberships/{id}/approve\|reject\|suspend\|revoke/` | verify / manage |
| `GET /institutions/{id}/memberships/{id}/verifications/{id}/document/` | `institution.memberships.verify` (audited) |
| `GET/POST /me/memberships/` | authenticated |
| `GET/PATCH/DELETE /me/memberships/{id}/` · `POST …/primary/` | owner |
| `GET/POST /me/memberships/{id}/verifications/` · `POST …/{vid}/complete/` | owner |

Related ids in requests (campus, unit, programme, level) are resolved **inside the institution in
the URL**. A reference to another institution's object is rejected.

## Events

`institution.created`, `institution.updated`, `institution.membership.requested`,
`institution.membership.verified`, `institution.joined`, `institution.membership.rejected`,
`institution.membership.suspended`, `institution.membership.revoked`,
`institution.membership.left`, `institution.verification.started`. Payloads contain ids only.

## Integration with Core

- **Profile**: `users.public_profile` adds verified affiliations when the user's
  `show_affiliations` privacy setting is on.
- **Export**: memberships are included in `/me/export/`.
- **Purge**: identifier hashes, evidence and verification documents are erased when an account is
  anonymised.
- **Content adapter**: `institution.institution` lets other modules show an institution's name
  (for example in notifications) and check its visibility. Active institutions are public;
  inactive ones are visible only to their managers. It is **display only**: institutions can't be
  reported, and moderation can't open cases or act on them. Enabling that needs an explicit
  policy: who investigates reports about an institution (platform trust and safety, not the
  institution's own staff) and which actions are allowed. Implement those actions in the adapter
  before setting `moderatable = True`.
- **Retention**: `institution.verification_documents`.
- **Throttles**: `institution_join` (10/day), `institution_verification` (10/hour).

## Importing data

`university_import_institutions <file.json|file.csv> [--verify-domains]` upserts by slug, so it's
idempotent. See the format in
[`importer.py`](../../packages/university-institution/src/university/institution/importer.py) and
the sample in `example_project/data/institutions.sample.json`. Only pass `--verify-domains` for
trusted sources.
