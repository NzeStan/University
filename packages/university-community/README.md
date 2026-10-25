# university-community

Communities for the [University platform](https://github.com/NzeStan/University):
public, restricted and private communities; institution, campus, department, club, interest and
creator communities. Members have owner, admin, moderator and member roles. This is an optional
*level two* module that depends only on `university-core`.

- Join instantly (public), on approval (restricted), or by invitation and invite link (private).
  Private communities are invisible to outsiders.
- Strict role hierarchy, with exactly one owner and explicit ownership transfer. Nobody can act on
  peers or superiors.
- Communities are **audiences**: community-only social posts, anonymous community boards and
  community-scoped moderation queues work automatically through Core hooks.
- Delegated moderation: community moderators moderate their own community. Communities linked to
  an institution stay under its managers' authority, and reports about a community itself go to
  the parent scope.
- Optional "members of this institution only", official recognition by the parent scope, invite
  links stored as hashes, audit trail, export and purge with ownership succession.

```bash
pip install university-community
```

```python
INSTALLED_APPS = [..., *CORE_APPS, "university.community"]
```

Guide: https://github.com/NzeStan/University/blob/main/docs/modules/community.md
