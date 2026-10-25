# university-media

Secure media: uploads, private object storage, asynchronous processing, signed streaming links,
clips and clean-up (spec §43, §44). It depends only on `university-core` and provides Core's
**media library**, so other modules (podcasts, and later posts or listings) use media by id
without importing this module.

```bash
pip install university-media
```

```python
INSTALLED_APPS += ["university.media"]
STORAGES = {
    "default": {...},
    "private": {
        "BACKEND": "storages.backends.s3.S3Storage",
        "OPTIONS": {"bucket_name": "uni-private", "querystring_auth": True},
    },
    "staticfiles": {...},
}
```

## Upload security

| Check | How |
| --- | --- |
| File type | **Content signature** (magic bytes) against the kind's allow-list; the client's `Content-Type` and file name are never trusted |
| Extension | must match the detected type |
| Dangerous content | executables, scripts and HTML/SVG/PHP are always rejected |
| Size | per kind (`MEDIA.KINDS[kind].max_bytes`), plus `STORAGE_QUOTA_BYTES_PER_USER` |
| Image dimensions | `max_pixels` (decompression-bomb protection, with Pillow) |
| Duration and video size | checked after probing (`max_duration_seconds`, `max_pixels`); failures are `too_long` or `too_large` |
| Names | random storage names under `media/originals/…`; the original name is kept only for display |
| Integrity | SHA-256 of every upload |

Kinds: `audio` (MP3, M4A, AAC, OGG, WAV, FLAC), `video` (MP4, MOV, WebM), `image` (JPEG, PNG,
WebP, GIF), `document` (PDF). People can have at most `MAX_PENDING_PER_USER` uploads processing
at once.

## Storage and direct uploads

Files live in the storage named by `MEDIA.STORAGE` (default `private`): S3, MinIO, GCS, or any
Django storage, never the app server's disk in production. Large files can bypass the API servers:

1. `POST media/uploads/` `{kind, mime_type, size, filename}` returns a short-lived presigned PUT
   (`MEDIA.DIRECT_UPLOADS`, for example `S3DirectUploadProvider`).
2. The client uploads straight to the bucket.
3. `POST media/uploads/{id}/complete/` checks the stored object's **size and content signature**
   before it becomes an asset. Disguised or oversized objects are deleted.

## Processing (asynchronous)

Every upload is processed on the task backend (Celery in production) and becomes `ready` or
`failed`, with a machine-readable `error`.

| Processor | Does |
| --- | --- |
| `BasicProcessor` (default) | image dimensions (Pillow), WAV duration and WAV clips; no external tools |
| `FFmpegProcessor` | probes duration and dimensions; makes `mp3` (audio, or a video's soundtrack), `mp4_720p` and `poster` renditions; cuts audio and video clips |

FFmpeg runs **sandboxed**: argument lists (never a shell), `-nostdin`, a timeout, limited
threads, and `-protocol_whitelist file`, so a hostile file such as a playlist pointing at URLs
can't make the server fetch anything. Implement `MediaProcessor` to use something else (for
example a cloud transcoder).

## Delivery

`MediaLibrary.url(media_id, variant=…)` returns a short-lived link:

- **`SERVE_MODE: "signed"`** (default): a signed, expiring link to `media/files/<token>/`. It
  streams the file with **HTTP Range** support (seeking in players), plus `nosniff` and
  `Content-Disposition: inline`. Tokens can't be forged or reused after expiry.
- **`SERVE_MODE: "storage"`:** the storage's own URL, such as an S3 presigned URL or a signed CDN.

Links are handed out only by consumers that have already decided the viewer may see the content.
For example, the podcast module redirects to a fresh link from a stable episode URL. Owners get
their own link in `GET media/{id}/`.

## The media library (for other modules)

```python
from university.core.media import require_media_library

library = require_media_library()
ref = library.attach(media_id, owner=user, purpose="podcast.episode", object_id=episode.pk)
ref.is_ready, ref.duration_seconds, ref.variants
url = library.url(media_id, variant="mp3")
clip = library.create_clip(media_id, owner=user, start_seconds=60, end_seconds=90)
library.detach(media_id, purpose="podcast.episode", object_id=episode.pk)
```

Only an asset's owner can attach it, so nobody can publish someone else's upload. Attached assets
can't be deleted by their owner (`409 media_in_use`). Clips are new assets processed
asynchronously, up to `CLIP_MAX_SECONDS`.

## API (`/api/v1/media/…`)

| Method & path | Who |
| --- | --- |
| `GET ./` · `POST ./` (multipart `file`, `kind?`) | the owner |
| `GET/DELETE {id}/` · `POST {id}/clips/` `{start_seconds, end_seconds}` | the owner |
| `POST uploads/` · `POST uploads/{id}/complete/` | the owner (direct uploads) |
| `GET files/{token}/` | anyone with a valid signed link |

Throttle: `media_upload` (60/hour).

## Operations

- **Retention:** `media.orphans` deletes uploads never attached to anything
  (`ORPHAN_RETENTION_HOURS`, 48); `media.failed` deletes failed uploads (`FAILED_RETENTION_DAYS`,
  7). Files are deleted from storage after the database commit.
- **Health check:** `media.processing` (non-critical) turns unhealthy when uploads stay unprocessed
  for more than two hours, usually because the worker is down.
- **Notifications:** with `university-notifications`, uploaders hear when processing fails.
- **Export and purge:** the export lists uploads; purge deletes them, files included.
