# university-podcast

Podcasts: shows, seasons, episodes, hosts, guests, audio, video, transcripts, clips, RSS and
listening analytics (spec §52). It depends only on `university-core`. Audio and video come from
Core's media library (`university-media`), and processing is asynchronous.

```bash
pip install university-podcast university-media
```

```python
INSTALLED_APPS += ["university.media", "university.podcast"]
```

A system check (`university_podcast.W001`) warns when no media library is installed.

## Shows and teams

- **Hosting:** a person (verified email, or `podcast.create` under
  `CREATION_POLICY: "permission"`) or a **scope**, such as a campus radio station, an institution
  or a community. Hosting for a scope needs `podcast.manage` there: the `podcast_manager` role, or
  community owners and admins by default.
- **Visibility:** `public`, `unlisted` (link only) or `audience` (members of the host scope).
  Drafts and moderation-hidden shows are visible only to managers.
- **Team:** `owner` (exactly one) > `host` > `producer`. All hold `podcast.manage` at the
  podcast's scope (implicit grants). People add or remove only roles below their own, and owners
  transfer ownership before leaving. The podcast is a permission child of its host scope.
- **Metadata:** category (`PODCAST.CATEGORIES`), language (`PODCAST.LANGUAGES`, including Hausa,
  Yoruba, Igbo, Swahili, Amharic, Zulu and Nigerian Pidgin), explicit flag, website (https),
  cover (an image from the media library), and seasons.

## Episodes

1. Upload audio and/or video to `POST /api/v1/media/`. Processing runs asynchronously.
2. `POST podcasts/{id}/episodes/` `{title, summary, show_notes, audio_media_id, video_media_id,
   season, number, episode_type, explicit}`. **Only media you uploaded** can be attached (Core's
   media library enforces ownership).
3. `POST podcasts/episodes/{id}/publish/` (optionally with `publish_at` to schedule). Publishing
   requires the media to be **ready**; the duration comes from processing. Scheduled episodes go
   live through `python manage.py publish_scheduled_episodes` (or its task). Subscribers are then
   notified.

`GET podcasts/episodes/{id}/stream/` (`?format=video`) is a **stable link** that redirects to a
fresh, short-lived media URL (the MP3 rendition when there is one). Players and RSS enclosures use
it, so nobody holds an expiring URL.

## Guests

Hosts add guests by name and bio, and optionally link an account (blocks apply). **A linked
account appears publicly only after the guest confirms** (`POST podcasts/guest-spots/{id}/respond/`
`{accept}`). Declining unlinks the account and keeps only the name.

## Transcripts

- **Upload:** `PUT podcasts/episodes/{id}/transcript/` `{content, format: vtt|srt|text, language}`.
  Input is untrusted: it's size-limited (`TRANSCRIPT_MAX_BYTES`), markup is stripped from cues,
  and timings are validated.
- **Read:** `GET …/transcript/` (text and cues) and `GET …/transcript.vtt` (for players and
  Podcasting 2.0 `podcast:transcript`).
- **Automatic** (an AI operation): `POST …/transcript/generate/` queues a task for the
  `PODCAST.TRANSCRIPTION_PROVIDER`, which implements `TranscriptionProvider.transcribe(audio_url,
  language)` (for example a Whisper service). The provider receives a short-lived signed link,
  never the file system.

## Clips

`POST podcasts/episodes/{id}/clips/` `{title, start_seconds, end_seconds}` cuts a clip
asynchronously through the media library (FFmpeg for audio and video; WAV with the basic
processor). Ready clips are listed at `GET …/clips/` and streamed via
`podcasts/clips/{id}/stream/`.

## RSS

`GET podcasts/{slug}/feed.xml` is available for **published public and unlisted** shows (never
members-only ones). It's RSS 2.0 with the `itunes` and Podcasting 2.0 namespaces: artwork,
category, explicit, `itunes:duration`, season and episode numbers, episode types, transcripts, and
enclosures pointing at the stable stream endpoint. All text is XML-escaped. Set
`PODCAST.PUBLIC_API_URL` to your public API origin.

## Listening analytics

`POST podcasts/episodes/{id}/plays/` `{position_seconds}` counts a play, and a completion past
`COMPLETION_THRESHOLD` (90%) of the duration, **at most once per listener per
`PLAY_DEDUPE_HOURS`**. De-duplication uses a short-lived keyed hash in the cache, and only daily
totals are stored. Managers read `GET podcasts/{id}/analytics/?from=&to=` (per-episode totals,
daily series, subscribers). Statistics are kept for `STATS_RETENTION_DAYS`.

## Trust and safety

Shows (`podcast.show`) and episodes (`podcast.episode`) **opt in to moderation**:

- **Who investigates:** the host scope's moderators, otherwise platform moderators.
- **Actions:** `hide` (managers only; can't be republished while hidden), `restore`, `remove`
  (soft-deletes and releases the media, which retention then cleans up).

Spam screening and content-creation restrictions apply.

## API (`/api/v1/…`)

| Method & path | Who |
| --- | --- |
| `GET/POST podcasts/` · `GET podcasts/by-slug/{slug}/` · `GET/PATCH podcasts/{id}/` | anyone / hosts |
| `POST podcasts/{id}/status/` `{publish\|archive}` · `GET podcasts/{id}/cover/` | managers / viewers |
| `GET/POST podcasts/{id}/members/` · `DELETE …/members/{user}/` · `POST …/transfer-ownership/` | viewers / managers |
| `GET/POST podcasts/{id}/seasons/` · `GET/POST podcasts/{id}/episodes/` | viewers / managers |
| `POST/DELETE podcasts/{id}/subscription/` · `GET podcasts/{id}/analytics/` | listeners / managers |
| `GET podcasts/{slug}/feed.xml` | anyone (public and unlisted shows) |
| `GET/PATCH/DELETE podcasts/episodes/{id}/` · `POST …/publish/` · `unpublish/` | viewers / managers |
| `GET …/stream/` · `POST …/plays/` | viewers |
| `POST …/guests/` · `DELETE …/guests/{id}/` · `POST podcasts/guest-spots/{id}/respond/` | managers / the guest |
| `GET/PUT …/transcript/` · `GET …/transcript.vtt` · `POST …/transcript/generate/` | viewers / managers |
| `GET/POST …/clips/` · `DELETE podcasts/clips/{id}/` · `GET podcasts/clips/{id}/stream/` | viewers / managers |
| `GET me/podcast-subscriptions/` · `GET me/podcasts/` | users |

## Operations

- **Scheduled job:** `publish_scheduled_episodes` (every minute or few).
- **Notifications** (with `university-notifications`): new episodes for subscribers (grouped per
  show), and guest invitations.
- **Export:** subscriptions, memberships and guest spots.
- **Purge:** subscriptions and guest links are removed. Owned shows pass to the highest-ranked
  remaining member, or are archived.
