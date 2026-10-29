# university-messaging

Direct and group messaging with message requests, read receipts and encryption at rest. It depends
only on `university-core` (and `cryptography`).

```bash
pip install university-messaging
```

```python
INSTALLED_APPS += ["university.messaging"]
UNIVERSITY = {"MESSAGING": {"ENCRYPTION_KEYS": [os.environ["MESSAGING_KEY"]]}}
```

Generate a key with `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`.
Keep it out of source control.

## Protection against unwanted messages

- A conversation someone new starts lands in the recipient's **Requests** until they accept (or
  reply). Members can turn requests off in `settings/`.
- Blocks (Core's `USER_CAN_INTERACT` hook) stop messaging. "Blocked" and "not accepting requests"
  return the **same** error, so a block is never revealed.
- Starting conversations and sending messages are rate limited; senders need a verified email.

## Endpoints (`/api/v1/messaging/`)

`GET/POST conversations/`, `GET conversations/{id}/`, `POST .../accept/`, `.../decline/`,
`.../read/`, `.../leave/`, `GET/POST .../participants/`, `GET/POST .../messages/`,
`PATCH/DELETE messages/{id}/` (edit within `EDIT_WINDOW_MINUTES`; delete leaves a tombstone),
`GET unread/`, `GET/PATCH settings/`.

## Storage

Message text is encrypted with Fernet before it's written. The first key in `ENCRYPTION_KEYS`
encrypts and every key decrypts, so keys can be rotated. Without keys, one is derived from
`SECURITY.HMAC_KEY`. Deleted messages are purged after `DELETED_RETENTION_DAYS`.

Messages are reportable: platform moderators see only the reported message, never the rest of the
conversation.

## Events

`messaging.message.sent` and `messaging.request.received` (ids only) drive notifications in the
`messages` category.
