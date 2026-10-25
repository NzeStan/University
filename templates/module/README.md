# university-__module_dist__

__description__

An optional **level-two** module of the University platform.

## Installation

```bash
pip install university-__module_dist__
```

```python
INSTALLED_APPS = [
    # ...
    *CORE_APPS,
    "university.__module__",
]
```

Run `python manage.py migrate`. The module's API is mounted automatically under
`/api/v1/__module__/`.

## Configuration

```python
UNIVERSITY = {
    "__MODULE__": {
        "ENABLED": True,
    },
}
```

## Permissions

| Code | Scope | Description |
| --- | --- | --- |
| `__module__.items.create` | platform | Create items |

## Events

| Event | Payload |
| --- | --- |
| `__module__.item.created` | `item_id`, `owner_id` |
