# university-opportunities

Jobs, internships, gigs, scholarships and volunteering for students, with applications and scam protection.

An optional **level-two** module of the University platform.

## Installation

```bash
pip install university-opportunities
```

```python
INSTALLED_APPS = [
    # ...
    *CORE_APPS,
    "university.opportunities",
]
```

Run `python manage.py migrate`. The module's API is mounted automatically under
`/api/v1/opportunities/`.

## Configuration

```python
UNIVERSITY = {
    "OPPORTUNITIES": {
        "ENABLED": True,
    },
}
```

## Permissions

| Code | Scope | Description |
| --- | --- | --- |
| `opportunities.items.create` | platform | Create items |

## Events

| Event | Payload |
| --- | --- |
| `opportunities.item.created` | `item_id`, `owner_id` |
