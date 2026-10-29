# university-opportunities

Jobs, internships, gigs, scholarships and volunteering for students, with in-app applications and
layered scam protection. It depends only on `university-core`.

```bash
pip install university-opportunities
```

```python
INSTALLED_APPS += ["university.opportunities"]
```

Schedule the `close_expired` task daily and the retention task weekly.

## What people can do

| Who | Can |
| --- | --- |
| Anyone signed in with a verified email | Post an opportunity (kind, organisation, pay range, location, work mode, deadline, audience) |
| Students | Browse and filter (`q`, `kind`, `work_mode`, `location`, `paid`, `institution`, `sort`), save, apply in-app with a cover note and a PDF CV, or follow an external link |
| Posters | Review applicants, shortlist, hire or reject, close or reopen a posting |
| Staff with `opportunities.verify` | Mark a poster as a **verified employer** |
| Moderators (`opportunities.moderate`) | Hide, restore or remove reported postings |

Opportunities can be public or limited to an audience (an institution's verified members) through
Core's audience scopes.

## Endpoints (`/api/v1/opportunities/`)

`GET/POST /`, `GET/PATCH/DELETE {id}/`, `POST {id}/status/`, `POST {id}/verify/`,
`POST {id}/apply/`, `GET {id}/applications/`, `POST/DELETE {id}/save/`, `GET me/posted/`,
`GET me/saved/`, `GET me/applications/`, `applications/{id}/` (the poster decides),
`POST applications/{id}/withdraw/`, `GET applications/{id}/resume/` (the CV, to the applicant and poster only).

## Privacy and safety

- CVs go to **private storage**, are checked by content (PDF signature, size), and are only served
  to the applicant and the poster. They're deleted `APPLICATION_RETENTION_DAYS` after closing.
- Posting needs a verified email, passes the spam filter and is capped per person
  (`MAX_OPEN_PER_USER`). "Verified employer" is only ever granted by staff.
- Reports: platform moderators investigate and may hide, restore or remove a posting.

## Events and notifications

`opportunities.application.submitted` notifies the poster; `opportunities.application.status_changed`
notifies the applicant when shortlisted, hired or rejected. Open postings are indexed by
university-search (`opportunities.opportunity`).

## Configuration

`UNIVERSITY["OPPORTUNITIES"]`: `REQUIRE_VERIFIED_EMAIL`, `MAX_OPEN_PER_USER`,
`DESCRIPTION_MAX_LENGTH`, `CURRENCIES`, `DEFAULT_CURRENCY`, `RESUME_MIME_TYPES`,
`RESUME_MAX_BYTES`, `APPLICATION_RETENTION_DAYS`, `AUTO_CLOSE_AFTER_DEADLINE`.
