# university-creator

The creator economy for the [University platform](https://github.com/NzeStan/University):
creator profiles, verification, linked social accounts, media kits, sponsorship campaigns and
analytics. This is an optional *level two* module that depends only on `university-core`.

- **Profiles** follow each user's own privacy settings and blocks. They carry categories, a
  verified badge on the public profile, and a discovery list with filters (category, country,
  verified, reach, open to sponsorships).
- **Verification.** Requests are reviewed by someone other than the creator; decisions are audited
  and can be revoked.
- **Linked accounts** (TikTok, Instagram, YouTube, X, Facebook, Spotify, Audiomack, Boomplay …):
  - Every platform sits behind a `SocialProvider` adapter.
  - Ownership is proven with a bio challenge code or confirmed by a reviewer.
  - Only confirmed follower counts count toward a creator's reach.
  - A verified account can belong to only one creator, which prevents impersonation.
  - No platform passwords or tokens are stored.
- **Media kits** have public, unlisted (revocable link) or private visibility, and hold validated
  audience breakdowns, a rate card, highlights and live platform stats.
- **Campaigns and sponsorships:**
  - Brands invite creators, or creators apply; brands shortlist and accept.
  - Slots are enforced in the database, and requirements (verified only, minimum reach) are
    checked on both paths.
  - Agreed fees, deliverables with review, and ad-disclosure confirmation are all supported.
  - Campaigns opt in to moderation, with reports going to the sponsor's moderators.
- **Analytics** are daily aggregates only (followers, reactions, comments, reposts, mentions,
  profile and media kit views, external follower growth). Views are de-duplicated without storing
  who viewed.

```bash
pip install university-creator
```

```python
INSTALLED_APPS += ["university.creator"]
```

See [the module documentation](../../docs/modules/creator.md).
