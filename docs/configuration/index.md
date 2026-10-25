# Configuration

All University configuration lives in one Django setting, `UNIVERSITY`. Core reads the top-level
keys below; each module owns one extra key (for example `INSTITUTION`). User values are
**deep-merged** over the defaults, so you only set what you change:

```python
UNIVERSITY = {
    "AUTH": {"JWT": {"ACCESS_TOKEN_LIFETIME_SECONDS": 600}},  # siblings keep their defaults
}
```

Values are read lazily and reloaded when the setting changes (for example under
`override_settings`). Unknown top-level keys trigger the `university.W001` system check, which
catches typos.

The authoritative defaults are in
[`university/core/defaults.py`](../../packages/university-core/src/university/core/defaults.py)
and [`university/institution/conf.py`](../../packages/university-institution/src/university/institution/conf.py).

Reading settings in code:

```python
from university.core.conf import university_settings, ModuleSettings

university_settings.get("AUTH.JWT.ALGORITHM")
university_settings.import_from("PROVIDERS.EMAIL")  # resolves a dotted path (cached)

my_settings = ModuleSettings("MYMODULE", {"ENABLED": True})  # for your own module
```

---

## `IDS`

| Key | Default | Description |
| --- | --- | --- |
| `UUID_VERSION` | `4` | `4` random (reveals nothing) or `7` time-ordered (better index locality at very large scale; embeds creation time). |

## `API`

| Key | Default | Description |
| --- | --- | --- |
| `URL_PREFIX` | `"api"` | Mount point of the versioned API. |
| `DEFAULT_VERSION` | `"v1"` | |
| `ALLOWED_VERSIONS` | `["v1"]` | Each version is a URL namespace; modules provide per-version URLconfs. |
| `SCHEMA_ENABLED` / `DOCS_ENABLED` | `True` | Serve `/api/schema/` and `/api/docs/` when drf-spectacular is installed. |

## `AUTH`

| Key | Default | Description |
| --- | --- | --- |
| `LOGIN_IDENTIFIERS` | `["email", "handle", "phone"]` | Accepted login identifiers (phone only if verified). |
| `TOKEN_ISSUER` | `JWTTokenIssuer` | Dotted path of the access-token issuer. Replace to change the token format. |
| `JWT.ALGORITHM` | `"HS256"` | Pinned algorithm (RS256/ES256/EdDSA supported with `VERIFYING_KEY`). |
| `JWT.SIGNING_KEY` | `None` | **Set in production.** `None` derives a key from `SECRET_KEY` (check W012). |
| `JWT.VERIFYING_KEY` | `None` | Public key for asymmetric algorithms. |
| `JWT.ISSUER` / `JWT.AUDIENCE` | `"university"` / `None` | Claims validated on every request. |
| `JWT.ACCESS_TOKEN_LIFETIME_SECONDS` | `300` | Keep short; refresh tokens handle longevity. |
| `JWT.LEEWAY_SECONDS` | `10` | Clock-skew tolerance. |
| `REFRESH_TOKEN_LIFETIME_SECONDS` | 30 days | Lifetime of each rotated refresh token. |
| `SESSION_MAX_AGE_SECONDS` | 90 days | Absolute session lifetime. |
| `SESSION_IDLE_TIMEOUT_SECONDS` | 14 days | A session unused this long cannot be refreshed. |
| `MAX_SESSIONS_PER_USER` | `25` | Oldest sessions are revoked beyond this. |
| `SESSION_TOUCH_INTERVAL_SECONDS` | `300` | Throttles `last_seen_at` writes. |
| `REVEAL_UNVERIFIED_ACCOUNT_ON_LOGIN` | `False` | Keep `False` to prevent enumeration. |
| `LOCKOUT.*` | 5 / 20 / 100 failures in 15 min, locked 15 min | Per identifier+IP, per identifier, per IP. |
| `API_KEYS.ENABLED` / `PREFIX` / `HEADER` | `True` / `"uk"` / `"X-API-Key"` | |
| `API_KEYS.MAX_PER_USER` / `DEFAULT_LIFETIME_DAYS` | `10` / `365` | |
| `MFA.ENABLED` / `MFA.CHANNELS` | `True` / `["email", "sms"]` | One-time-code second factor. |
| `PASSWORDLESS.ENABLED` | `False` | Email/SMS code sign-in. |
| `IDENTITY_PROVIDERS` | `{}` | OAuth/OIDC providers: `{"google": {"CLASS": ..., "OPTIONS": {...}}}`. |
| `LINK_EXTERNAL_IDENTITY_BY_VERIFIED_EMAIL` | `False` | Auto-link by verified email. Off by default (takeover risk). |
| `ALLOW_SIGNUP_VIA_IDENTITY_PROVIDER` | `True` | |

## `SECURITY`

| Key | Default | Description |
| --- | --- | --- |
| `HMAC_KEY` | `None` | **Set in production.** Keys hashes of tokens, OTPs, identifiers and audit entries (falls back to `SECRET_KEY`). |
| `HMAC_KEY_FALLBACKS` | `[]` | Old keys, still accepted during rotation. |
| `TRUSTED_PROXY_COUNT` | `0` | Number of reverse proxies in front of the app. `0` ignores `X-Forwarded-For`. |
| `CLIENT_IP_HEADER` | `"HTTP_X_FORWARDED_FOR"` | |
| `STORE_FULL_IP_ADDRESSES` | `True` | `False` truncates stored IPs to /24 (/48 for IPv6). |
| `SUSPICIOUS_LOGIN_DETECTOR` | heuristic | Dotted path; plug in geo-IP or risk services. |
| `SEND_LOGIN_ALERT_EMAILS` | `True` | |
| `TRUST_INCOMING_REQUEST_ID` | `False` | Accept `X-Request-ID` from a trusted edge. |
| `API_CONTENT_SECURITY_POLICY` / `API_CACHE_CONTROL` | locked down / `"no-store"` | Applied to API responses. |

## `OTP`

`LENGTH` (6), `TTL_SECONDS` (600), `MAX_ATTEMPTS` (5), `RESEND_COOLDOWN_SECONDS` (60),
`MAX_ISSUES_PER_DESTINATION_PER_HOUR` (5).

## `USERS`

| Key | Default | Description |
| --- | --- | --- |
| `ALLOW_REGISTRATION` | `True` | |
| `REGISTRATION_MODE` | `"verify_first"` | `verify_first` (no enumeration; activation by email) or `open` (tokens immediately). |
| `HANDLE_MIN_LENGTH` / `HANDLE_MAX_LENGTH` | `3` / `30` | |
| `RESERVED_HANDLES` | admin, support, … | |
| `EMAIL_VERIFICATION_TTL_SECONDS` / `EMAIL_CHANGE_TTL_SECONDS` | 3 days / 1 day | |
| `DELETION_GRACE_PERIOD_DAYS` | `30` | After this, deleted accounts are anonymised. |
| `DEFAULT_PROFILE_VISIBILITY` | `"public"` | |
| `FRONTEND_URLS` | localhost templates | Links in emails; `{token}` and `{uid}` are substituted. |
| `ME_SERIALIZER` / `PUBLIC_PROFILE_SERIALIZER` | `None` | Dotted paths to override serializers without forking. |
| `CONSENT_PURPOSES` | terms, privacy, marketing | |

## `PROVIDERS`

| Key | Default | Alternatives |
| --- | --- | --- |
| `EMAIL` | `DjangoEmailProvider` | Any class with `send(message)`; Django's backend supports SMTP and django-anymail (SES, SendGrid, Mailgun, Postmark …). |
| `SMS` | `ConsoleSMSProvider` (dev only) | `TermiiSMSProvider`, `TwilioSMSProvider`, `AfricasTalkingSMSProvider`, `NullSMSProvider`, or your own. |
| `SMS_OPTIONS` | `{}` | Constructor kwargs, e.g. `{"api_key": ..., "sender_id": ...}`. |
| `SEARCH` | `NullSearchBackend` | Provided by `university-search` (planned). |
| `SPAM` | `RuleBasedSpamFilter` | `NullSpamFilter`, or AI/third-party filters in their own packages. |

## `TASKS`

| Key | Default | Description |
| --- | --- | --- |
| `BACKEND` | `ImmediateTaskBackend` | `CeleryTaskBackend` or `DjangoTaskBackend` in production (check W013). |
| `EAGER_PROPAGATE_EXCEPTIONS` | `False` | Re-raise in the immediate backend (tests). |
| `QUEUES` | `{}` | Celery routing: `{"task.name": "queue"}`. |

## `EVENTS`

`DISPATCH_ON_COMMIT` (`True`): handlers run after the transaction commits.
`RAISE_HANDLER_ERRORS` (`False`): set `True` in tests.

## `PAGINATION`

`PAGE_SIZE` (20), `MAX_PAGE_SIZE` (100). Clients pass `?page_size=`.

## `THROTTLE_RATES`

`"<count>/<period>"`, where the period is `s`, `min`, `hour` or `day`, optionally with a
multiplier (`"100/15min"`). `None` disables a scope. Core scopes: `anon_global`, `user_global`,
`login`, `token_refresh`, `registration`, `password_reset`, `password_change`,
`email_verification`, `otp_request`, `otp_verify`, `account_delete`, `data_export`,
`api_key_create`, `profile_lookup`, `upload`, `report`, `webhook`. Modules contribute defaults for
their own scopes (for example `institution_join`), and values set here always take precedence.

## `AUDIT`

`ENABLED` (`True`), `HASH_CHAIN` (`False`; chains entries but serialises audit writes),
`METADATA_MAX_BYTES` (8192), `SINKS` (`["university.audit.sinks.DatabaseSink"]`; add
`LoggingSink` to stream entries to a SIEM).

## `RETENTION`

`AUDIT_LOG_DAYS` (730), `LOGIN_ATTEMPT_DAYS` (90), `OTP_CHALLENGE_DAYS` (7),
`REVOKED_SESSION_DAYS` (90), `IDEMPOTENCY_RECORD_HOURS` (48), `WEBHOOK_EVENT_DAYS` (30).
`None` disables a policy. Run `manage.py university_purge` (or schedule the
`university.core.purge` task).

## `UPLOADS`, `IDEMPOTENCY`, `WEBHOOKS`, `CACHE`, `PLUGINS`, `HEALTH`, `PERMISSIONS`

| Key | Default |
| --- | --- |
| `UPLOADS.MAX_BYTES` / `ALLOWED_MIME_TYPES` / `MAX_IMAGE_PIXELS` | 10 MB / images + PDF / 40 MP |
| `IDEMPOTENCY.HEADER` / `LOCK_SECONDS` | `"Idempotency-Key"` / 30 |
| `WEBHOOKS.TIMESTAMP_TOLERANCE_SECONDS` | 300 |
| `CACHE.ALIAS` / `KEY_PREFIX` / `PERMISSIONS_TTL_SECONDS` | `"default"` / `"university"` / 300 |
| `PLUGINS.LOAD_ENTRY_POINTS` / `ENTRY_POINT_GROUP` / `DISABLED` | `True` / `"university.plugins"` / `[]` |
| `HEALTH.READINESS_CHECKS` | `["database", "cache"]` plus module checks |
| `PERMISSIONS.SUPERUSER_BYPASS` | `True` |

---

## `INSTITUTION` (university-institution)

| Key | Default | Description |
| --- | --- | --- |
| `INSTITUTION_TYPES` | university, polytechnic, college of education, monotechnic, health, vocational, other | Seeded on migrate; edit in admin. |
| `OWNERSHIP_TYPES` | public, private, faith-based, community, other | |
| `ACADEMIC_UNIT_TYPES` | college, faculty, school, department, institute, centre, unit | |
| `QUALIFICATION_LEVELS` | certificate … doctorate, ND, HND, NCE | |
| `STUDY_MODES` | full-time, part-time, distance, sandwich, online | |
| `MEMBERSHIP_ROLES` | student, staff, lecturer, administrator, alumni, guest, moderator, organization | |
| `AUTO_VERIFY_ROLES` | `["guest"]` | |
| `ALLOW_MULTIPLE_INSTITUTIONS` | `True` | |
| `MAX_ACTIVE_MEMBERSHIPS_PER_USER` | `5` | |
| `VERIFICATION_PROVIDERS` | email, student_id, document, manual | `{key: dotted path}`; add your own. |
| `DEFAULT_VERIFICATION_METHODS` | `["institution_email", "manual"]` | Used when an institution lists none. |
| `DOCUMENT_MAX_BYTES` / `DOCUMENT_MIME_TYPES` | 5 MB / PDF, JPEG, PNG | |
| `VERIFICATION_DOCUMENT_RETENTION_DAYS` | `90` | Documents are deleted after the decision. |
| `VERIFICATION_REQUEST_TTL_DAYS` | `30` | |

---

## `SOCIAL` (university-social)

| Key | Default | Description |
| --- | --- | --- |
| `POST_MAX_LENGTH` / `COMMENT_MAX_LENGTH` | `5000` / `2000` | |
| `DEFAULT_VISIBILITY` | `"public"` | Users can override it per profile (`default_post_visibility`). |
| `SCOPED_VISIBILITIES` | `["institution", "campus", "community"]` | Visibilities that restrict a post to an audience scope. |
| `REACTION_TYPES` | like, love, laugh, wow, sad, angry, support | |
| `MAX_HASHTAGS_PER_POST` / `MAX_MENTIONS_PER_POST` / `MAX_LINKS_PER_POST` | `10` / `20` / `5` | |
| `MAX_MEDIA_PER_POST` / `MEDIA_MAX_BYTES` / `MEDIA_MIME_TYPES` | `4` / 10 MB / JPEG, PNG, GIF, WebP | |
| `ORPHAN_MEDIA_HOURS` | `24` | Unattached uploads are deleted after this. |
| `EDIT_WINDOW_MINUTES` | `1440` | `None` allows editing at any time. |
| `LOCATION_ENABLED` | `False` | |
| `POLL_MIN_OPTIONS` / `POLL_MAX_OPTIONS` / `POLL_MAX_DURATION_DAYS` | `2` / `4` / `14` | |
| `FEEDS` | home, explore, trending | `{name: dotted path}`; add or replace providers. |
| `HOME_INCLUDES_MEMBER_SCOPES` | `True` | Include audience posts in the home feed. |
| `RANKING` | 72 h window, 500 candidates, gravity 1.5, weights 1/2/3 | Trending formula parameters. |

Throttle scopes contributed: `social_post` (30/hour), `social_comment` (120/hour),
`social_reaction` (600/hour), `social_follow` (200/day), `social_media_upload` (60/hour).

---

## `MODERATION` (university-moderation)

| Key | Default | Description |
| --- | --- | --- |
| `REASONS` | 13 reasons (spam … other) | Seeded on migrate; `{key, label, severity, requires_details}`. |
| `SEVERITY_WEIGHTS` | low 1, medium 2, high 4, critical 8 | Queue priority = max weight × 10 + reports. |
| `DEFAULT_RULES` | report threshold (5) → hide; critical reason → hide | Seeded on migrate; only reversible actions are allowed. |
| `APPEAL_WINDOW_DAYS` | `14` | |
| `APPEALS_REQUIRE_DIFFERENT_MODERATOR` | `True` | Four-eyes review. |
| `MAX_RESTRICTION_DAYS` | `365` | |
| `RESOLVED_CASE_RETENTION_DAYS` | `730` | Actions are kept. |
| `EXCERPT_LENGTH` | `500` | Evidence snapshot length. |

## `ANONYMOUS` (university-anonymous)

| Key | Default | Description |
| --- | --- | --- |
| `ALLOWED_VISIBILITIES` | institution, campus, community | Add `public` to allow platform-wide anonymous posts. |
| `POST_MAX_LENGTH` / `COMMENT_MAX_LENGTH` | `3000` / `1000` | |
| `MIN_ACCOUNT_AGE_HOURS` / `REQUIRE_VERIFIED_EMAIL` | `24` / `True` | Posting gates. |
| `TIMESTAMP_PRECISION_SECONDS` | `300` | Stored and displayed times are rounded down. |
| `IDENTITY_KEYS` | `[]` | **Set in production.** Fernet keys; the first encrypts, all decrypt. |
| `REVEAL_REQUIRES_APPROVAL` / `REVEAL_APPROVAL_TTL_HOURS` / `REVEAL_MIN_JUSTIFICATION` | `True` / `24` / `30` | Two-person rule. |
| `SHOW_OP_LABEL` | `True` | |
| `REACTION_TYPES` | like, support, laugh, sad | |
| `PSEUDONYM_ADJECTIVES` / `PSEUDONYM_NOUNS` | 20 × 30 words | Localise freely. |

Throttle scopes: `anonymous_post` (5/hour), `anonymous_post_daily` (20/day), `anonymous_comment`
(30/hour), `anonymous_reaction` (300/hour), `anonymous_reveal` (10/day).

---

## `COMMUNITY` (university-community)

| Key | Default | Description |
| --- | --- | --- |
| `KINDS` | interest, institution, campus, department, club, creator, study_group, other | |
| `CREATION_POLICY` | `"verified_users"` | Or `"permission"` (requires `community.create`). |
| `MAX_OWNED_COMMUNITIES` / `MAX_MEMBERSHIPS_PER_USER` | `10` / `500` | |
| `INVITE_LINK_MAX_DAYS` | `30` | |
| `EXPIRED_INVITE_LINK_RETENTION_DAYS` | `30` | |
| `ROLE_PERMISSIONS` | see the community guide | Permissions each role holds at its community's scope. |

Throttle scopes: `community_create` (5/day), `community_join_code` (30/hour).

---

## `NOTIFICATIONS` (university-notifications)

| Key | Default | Description |
| --- | --- | --- |
| `CATEGORIES` | security, moderation, account, communities, events, creator, commerce, podcasts, media, mentions, comments, follows, reactions, reposts | Per-channel defaults (`email`: False / `"immediate"` / `"digest"`), `mandatory`, `bypass_quiet_hours`. |
| `DISABLED_VERBS` | `[]` | Verb keys to switch off, e.g. `["social.reaction"]`. |
| `CHANNELS` | email, push, sms | Dotted paths; `None` disables a channel. |
| `PUSH_PROVIDER` / `PUSH_PROVIDER_OPTIONS` | `NullPushProvider` / `{}` | Or `FCMPushProvider`, `ExpoPushProvider`. |
| `PUSH_PREVIEWS` | `True` | `False` sends generic text to lock screens. |
| `PUSH_MAX_PER_HOUR` | `30` | Per person; extra pushes are suppressed. |
| `MAX_DEVICES_PER_USER` | `10` | Older devices are retired. |
| `MAX_DELIVERY_ATTEMPTS` / `RETRY_BASE_SECONDS` | `5` / `60` | Exponential backoff. |
| `DIGEST_MAX_ITEMS` | `20` | |
| `OPEN_URL` / `LIST_URL` / `PREFERENCES_URL` / `SITE_NAME` | localhost URLs / `"University"` | Used in emails and push payloads; `{id}` is the notification id. |
| `ASYNC_HANDLERS` | `False` | Handle events on the task backend. |
| `READ_RETENTION_DAYS` / `UNREAD_RETENTION_DAYS` | `90` / `365` | |
| `DELIVERY_RETENTION_DAYS` / `DISABLED_DEVICE_RETENTION_DAYS` | `30` / `30` | |
| `DEVICE_STALE_DAYS` | `270` | Devices unseen this long stop receiving pushes. |

Throttle scopes: `notifications_device_register` (30/hour).

---

## `EVENTS` (university-events)

| Key | Default | Description |
| --- | --- | --- |
| `CATEGORIES` | academic, career, social, sports, arts, religious, tech, workshop, conference, community, other | |
| `CREATION_POLICY` | `"verified_users"` | Or `"permission"` (requires `events.create`). Hosting for a scope always needs `events.manage` there. |
| `MAX_UPCOMING_EVENTS_PER_USER` | `20` | |
| `MAX_DURATION_DAYS` / `MAX_TICKET_TYPES` / `MAX_SESSIONS` / `MAX_ORGANIZERS` | `30` / `10` / `100` / `20` | |
| `PAID_TICKETS_ENABLED` | `False` | Needs a payments module (see the events guide). |
| `DEFAULT_CURRENCY` / `CURRENCIES` | `"NGN"` / NGN, GHS, KES, ZAR, XOF, EGP, USD | |
| `PAYMENT_HOLD_MINUTES` | `15` | |
| `WAITLIST_AUTO_PROMOTE` | `True` | |
| `REMINDER_HOURS` | `24` | |
| `EVENT_URL` | `http://localhost:3000/events/{slug}` | Used in calendar files. |
| `COVER_MIME_TYPES` / `COVER_MAX_BYTES` | JPEG, PNG, WebP / 5 MB | |
| `REFUND_ON_ATTENDEE_CANCEL` / `REFUND_CUTOFF_HOURS` | `True` / `24` | Paid tickets cancelled by attendees are refunded until the cutoff. |
| `REGISTRATION_RETENTION_DAYS` | `730` | |

Throttle scopes: `events_create` (10/day), `events_venue_create` (20/day), `events_register`
(30/hour), `events_checkin` (1200/hour).

---

## `CREATOR` (university-creator)

| Key | Default | Description |
| --- | --- | --- |
| `CATEGORIES` | music, comedy, education, tech, fashion, … other | Seeded on migrate; edit in the admin afterwards. |
| `MAX_CATEGORIES_PER_PROFILE` | `3` | |
| `PROVIDERS` | TikTok, Instagram, YouTube, X, Facebook, Spotify, LinkedIn, Twitch, Audiomack, Boomplay | `{key: {"label", "url", "class"?, "options"?}}`; `None` removes one. |
| `MAX_LINKED_ACCOUNTS` | `15` | |
| `SYNC_INTERVAL_HOURS` | `24` | |
| `CAMPAIGN_POLICY` | `"verified_users"` | Or `"permission"` (requires `creator.campaigns.manage`). |
| `MAX_OPEN_CAMPAIGNS_PER_USER` / `MAX_DELIVERABLES` | `10` / `30` | |
| `CURRENCIES` / `DEFAULT_CURRENCY` | NGN, GHS, KES, ZAR, XOF, EGP, USD / `"NGN"` | |
| `DISCLOSURE_REQUIRED_BY_DEFAULT` | `True` | Creators confirm #ad labelling on submission. |
| `PLATFORM_FEE_BPS` | `0` | Commission on paid sponsorship fees. |
| `ANALYTICS_RETENTION_DAYS` / `ANALYTICS_MAX_RANGE_DAYS` | `730` / `366` | |
| `VIEW_DEDUPE_HOURS` | `24` | |
| `PROFILE_URL` | `http://localhost:3000/creators/{handle}` | |

Throttle scopes: `creator_verification`, `creator_link_account`, `creator_verify_account`,
`creator_campaign_create`, `creator_campaign_apply`, `creator_campaign_invite` (see the creator
guide).

---

## `PAYMENTS` (university-payments)

| Key | Default | Description |
| --- | --- | --- |
| `PROVIDERS` | `{}` | `{key: {"class": ..., "options": {...}}}`; keys appear in webhook URLs. |
| `DEFAULT_PROVIDER` | `None` | Used when a checkout names none (or the only configured one). |
| `CALLBACK_URL` | `http://localhost:3000/payments/return?reference={reference}` | |
| `ALLOWED_CALLBACK_PREFIXES` | `["http://localhost:3000/"]` | Client callback URLs must match (open-redirect protection). |
| `CURRENCIES` | NGN, GHS, KES, ZAR, XOF, EGP, USD | |
| `INTENT_TTL_MINUTES` | `60` | |
| `MAX_REFUND_ATTEMPTS` | `5` | |
| `MIN_PAYOUT_MINOR` | per currency (NGN 1,000 …) | |

Throttle scopes: `payments_checkout` (30/hour), `payments_payout` (10/day).

---

## `MARKETPLACE` (university-marketplace)

| Key | Default | Description |
| --- | --- | --- |
| `CATEGORIES` | electronics (phones, laptops, accessories), books, fashion, hostel, services, food, other | Seeded tree. |
| `CURRENCIES` / `DEFAULT_CURRENCY` | NGN, … / `"NGN"` | |
| `PLATFORM_FEE_BPS` | `0` | Commission on online orders (basis points). |
| `REQUIRE_VERIFIED_EMAIL` | `True` | |
| `MAX_ACTIVE_LISTINGS` / `MAX_QUANTITY_PER_ORDER` / `MAX_IMAGES` | `50` / `20` / `8` | |
| `IMAGE_MIME_TYPES` / `IMAGE_MAX_BYTES` | JPEG, PNG, WebP / 5 MB | |
| `ALLOW_CASH_ON_PICKUP` | `True` | |
| `PAYMENT_WINDOW_MINUTES` | `30` | Unpaid orders release stock. |
| `AUTO_COMPLETE_DAYS` | `7` | Dispute window before escrow is released automatically. |
| `DELIVERY_DETAILS_RETENTION_DAYS` | `30` | |

Throttle scopes: `marketplace_listing_create` (30/day), `marketplace_order` (30/hour).

---

## `MEDIA` (university-media)

| Key | Default | Description |
| --- | --- | --- |
| `KINDS` | audio, video, image, document | Per kind: `mime_types`, `max_bytes`, `max_duration_seconds`, `max_pixels`. |
| `STORAGE` | `"private"` | Django storage alias for originals and renditions. |
| `SERVE_MODE` | `"signed"` | Or `"storage"` (presigned / CDN URLs from the storage). |
| `SIGNED_URL_TTL_SECONDS` | `3600` | |
| `PUBLIC_BASE_URL` | `""` | Prefix for absolute signed links. |
| `PROCESSOR` / `PROCESSOR_OPTIONS` | `BasicProcessor` / `{}` | Or `FFmpegProcessor` (`ffmpeg`, `ffprobe`, `timeout`, `threads`). |
| `DIRECT_UPLOADS` | `None` | `{"class": "...S3DirectUploadProvider", "options": {"bucket": ...}}`. |
| `DIRECT_UPLOAD_TTL_SECONDS` | `900` | |
| `STORAGE_QUOTA_BYTES_PER_USER` | 5 GB | |
| `MAX_PENDING_PER_USER` | `10` | |
| `CLIP_MAX_SECONDS` | `180` | |
| `ORPHAN_RETENTION_HOURS` / `FAILED_RETENTION_DAYS` | `48` / `7` | |

Throttle scope: `media_upload` (60/hour).

---

## `PODCAST` (university-podcast)

| Key | Default | Description |
| --- | --- | --- |
| `CATEGORIES` | Arts … TV & Film (17) | |
| `LANGUAGES` | en, fr, pt, ar, sw, ha, yo, ig, am, zu, pcm | |
| `CREATION_POLICY` | `"verified_users"` | Or `"permission"` (requires `podcast.create`). |
| `MAX_PODCASTS_PER_USER` / `MAX_MEMBERS` / `MAX_GUESTS_PER_EPISODE` | `5` / `10` / `10` | |
| `PUBLIC_API_URL` | `http://localhost:8000` | Origin for RSS links. |
| `SHOW_URL` | `http://localhost:3000/podcasts/{slug}` | |
| `TRANSCRIPT_MAX_BYTES` | 2 MB | |
| `TRANSCRIPTION_PROVIDER` | `None` | Dotted path, or `{"class", "options"}`. |
| `COMPLETION_THRESHOLD` / `PLAY_DEDUPE_HOURS` | `0.9` / `24` | |
| `STATS_RETENTION_DAYS` | `730` | |

Throttle scope: `podcast_create` (5/day).

---

## `ANALYTICS` (university-analytics)

| Key | Default | Description |
| --- | --- | --- |
| `TRACK` | user, social, community, institution, events, marketplace, creator, podcast … patterns | Event-name patterns counted daily. |
| `EXCLUDE` | `*.notice`, `notifications.*`, `security.*`, `events.attendee.*` | Win over `TRACK`. |
| `DIMENSIONS` | `institution_id`, `community_id`, `campus_id` | Payload keys that add per-scope breakdowns. |
| `ACTIVE_USERS` | `True` | Daily/weekly/monthly unique actives (needs a shared cache). |
| `MIN_REPORTABLE` | `5` | Scope reports suppress smaller counts. |
| `VIEW_DEDUPE_HOURS` | `24` | |
| `RETENTION_DAYS` / `MAX_RANGE_DAYS` | `1095` / `366` | |
| `SINKS` | `[]` | e.g. `["university.analytics.sinks.LogSink"]`. |

Throttle scope: `analytics_view` (600/hour).

---

## `TRENDING` (university-trending)

| Key | Default | Description |
| --- | --- | --- |
| `SIGNALS` | views, reactions, comments, shares, registrations, joins, orders | Event -> item and signal. |
| `WEIGHTS` | view 0.2, reaction 1, comment 3, share 5, registration 4, join 3, order 4 | |
| `WINDOW_HOURS` / `VELOCITY_HOURS` | `48` / `6` | |
| `VELOCITY_WEIGHT` / `GRAVITY` | `1.0` / `1.5` | |
| `MIN_UNIQUE_ACTORS` / `DEDUPE_HOURS` / `MAX_PER_AUTHOR` | `2` / `24` / `2` | Anti-gaming and diversity. |
| `MAX_ITEMS_PER_TYPE` | `500` | |
| `ALGORITHM` | `university.trending.algorithms.GravityVelocity` | |
| `SIGNAL_RETENTION_HOURS` | `168` | |

---

## `SEARCH` (university-search)

| Key | Default | Description |
| --- | --- | --- |
| `SOURCES` | posts, comments, anonymous posts, communities, events, listings, episodes, campaigns | Type -> index/remove events and id key. |
| `BACKEND` / `BACKEND_OPTIONS` | `None` / `{}` | e.g. `university.search.backends.OpenSearchBackend` with `url`, `api_key`. |
| `MIN_QUERY_LENGTH` / `MAX_QUERY_LENGTH` / `MAX_RESULTS` | `2` / `100` / `50` | |
| `PEOPLE_MIN_QUERY_LENGTH` / `PEOPLE_MAX_RESULTS` | `3` / `20` | |
| `ASYNC_INDEXING` | `True` | |

Throttle scopes: `search` (120/minute), `search_people` (30/minute).
