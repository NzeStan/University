# university-promotions

Sponsored posts, boosts and ads with review, budgets and privacy-preserving delivery stats.

An optional **level-two** module of the University platform.

## Installation

```bash
pip install university-promotions
```

```python
INSTALLED_APPS = [
    # ...
    *CORE_APPS,
    "university.promotions",
]
```

Run `python manage.py migrate`. The module's API is mounted automatically under
`/api/v1/promotions/`.

## Configuration

```python
UNIVERSITY = {
    "PROMOTIONS": {
        "ENABLED": True,
    },
}
```

## Permissions

| Code | Scope | Description |
| --- | --- | --- |
| `promotions.items.create` | platform | Create items |

## Events

| Event | Payload |
| --- | --- |
| `promotions.item.created` | `item_id`, `owner_id` |
