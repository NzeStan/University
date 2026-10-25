# university-institution

Institutions, campuses, academic structure and **verified memberships** for the
[University platform](https://github.com/NzeStan/University). This is an optional
*level two* module that depends only on `university-core`.

- Configurable institution types (university, polytechnic, college of education, monotechnic …),
  with no hard-coded institutions or countries.
- Institutions are tenant and permission scopes; campuses resolve to their institution.
- A flexible academic tree (college / faculty / school / department / …), programmes, levels,
  sessions and semesters.
- Multi-institution memberships with configurable roles and a full lifecycle.
- **Pluggable verification**: institutional email + OTP, student/staff number review (stored only
  as keyed hashes), document review (private storage, automatic deletion) and manual review.
  You can add your own provider.
- Scoped administrator and verifier roles, audited decisions, events, data export and purge hooks,
  and an idempotent JSON/CSV importer.

```bash
pip install university-institution
```

```python
INSTALLED_APPS = [..., *CORE_APPS, "university.institution"]
```

```bash
python manage.py migrate
python manage.py university_import_institutions institutions.json
```

The API mounts automatically under `/api/v1/`. Full guide:
https://github.com/NzeStan/University/blob/main/docs/modules/institution.md
