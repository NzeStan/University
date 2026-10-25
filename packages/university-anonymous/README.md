# university-anonymous

Anonymous posts and comments for the [University platform](https://github.com/NzeStan/University):
**unlinkable to the public, accountable to the platform.**

- Authors are never exposed: not in API responses, errors, events, exports, or to ordinary
  moderators.
- Authorship is never stored in plaintext. Ownership is proven with a per-item keyed hash, and the
  identity is kept only Fernet-encrypted (with key rotation). A database dump alone links no
  author to any item.
- Revealing an author needs a sensitive permission, a written justification and a **second
  person's approval**. Approvals expire, and every step and every retrieval is audited.
- Abuse controls are built in: it requires `university-moderation`, posts are limited to audiences
  (institution/campus/community), and posting needs a verified email and a minimum account age.
  Rate limits, spam screening, sanctions and appeals also apply.
- Per-thread pseudonyms ("Quiet Heron", "OP") keep conversations readable without linking a
  user's activity across threads.
- Random UUIDv4 IDs and coarsened timestamps defeat timing correlation. Blocks deliberately don't
  hide anonymous posts (that would let people unmask authors); users can hide posts instead.

```bash
pip install university-anonymous   # pulls in university-moderation and cryptography
```

```python
INSTALLED_APPS = [..., *CORE_APPS, "university.moderation", "university.anonymous"]
UNIVERSITY = {"ANONYMOUS": {"IDENTITY_KEYS": [env("ANONYMOUS_IDENTITY_KEY")]}}
```

Guide: https://github.com/NzeStan/University/blob/main/docs/modules/anonymous.md
