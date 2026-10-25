# university-moderation

Reports, moderation cases, actions, appeals and explainable automated rules for the
[University platform](https://github.com/NzeStan/University). It is an optional
*level two* module that depends only on `university-core`, and it moderates **any** content type
registered through Core content adapters (social posts, anonymous posts, accounts …) without
importing the modules that own them.

- Configurable report reasons with severities, prioritised queues, and an evidence snapshot per
  case.
- Queues and authority scoped to the content's audience: an institution's moderators see and act
  on that institution's content only.
- Actions: dismiss, warn, hide, remove, restore, restrict (time-boxed, enforced across modules
  through Core's `content.can_create` hook), suspend and ban. Everything is audited, and there's
  a conflict-of-interest guard.
- Appeals decided by a different moderator (four-eyes), with automatic reversal on overturn.
- Automated rules that are reversible, explainable and always leave the final decision to a human.
- Anonymous content is handled without exposing or storing its author.

```bash
pip install university-moderation
```

```python
INSTALLED_APPS = [..., *CORE_APPS, "university.moderation"]
```

Guide: https://github.com/NzeStan/University/blob/main/docs/modules/moderation.md
