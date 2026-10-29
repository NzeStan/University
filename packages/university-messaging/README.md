# university-messaging

Direct and group messaging with message requests, read receipts and encryption at rest.

An optional **level-two** module of the University platform.

## Installation

```bash
pip install university-messaging
```

```python
INSTALLED_APPS = [
    # ...
    *CORE_APPS,
    "university.messaging",
]
```

Run `python manage.py migrate`. The module's API is mounted automatically under
`/api/v1/messaging/`.

## Configuration

```python
UNIVERSITY = {
    "MESSAGING": {
        "ENABLED": True,
    },
}
```

## Permissions

| Code | Scope | Description |
| --- | --- | --- |
| `messaging.items.create` | platform | Create items |

## Events

| Event | Payload |
| --- | --- |
| `messaging.item.created` | `item_id`, `owner_id` |
