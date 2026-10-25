"""RSS 2.0 feed with the Apple Podcasts (itunes) and Podcasting 2.0 (podcast) namespaces.

Enclosures and artwork point at stable API endpoints that redirect to fresh,
short-lived media links, so podcast apps never hold expiring URLs.
"""

from __future__ import annotations

import html
from email.utils import format_datetime
from typing import Any

from django.urls import reverse

from university.core.media import get_media_library
from university.podcast.conf import podcast_settings
from university.podcast.selectors import live_episodes


def escape(value: str) -> str:
    """Escape text content for XML (we only ever generate XML; nothing is parsed here)."""
    return html.escape(value or "", quote=False)


def quoteattr(value: str) -> str:
    return f'"{html.escape(value or "", quote=True)}"'


def _abs(path: str) -> str:
    return f"{str(podcast_settings.get('PUBLIC_API_URL')).rstrip('/')}{path}"


def _duration(seconds: float | None) -> str:
    total = int(seconds or 0)
    return f"{total // 3600:02d}:{total % 3600 // 60:02d}:{total % 60:02d}"


def build_feed(podcast: Any) -> str:
    library = get_media_library()
    show_url = str(podcast_settings.get("SHOW_URL")).format(slug=podcast.slug)
    self_url = _abs(reverse("v1:podcast:feed", kwargs={"slug": podcast.slug}))
    out = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<rss version="2.0" xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd" '
        'xmlns:podcast="https://podcastindex.org/namespace/1.0" xmlns:atom="http://www.w3.org/2005/Atom">',
        "<channel>",
        f"<title>{escape(podcast.title)}</title>",
        f"<link>{escape(show_url)}</link>",
        f'<atom:link href={quoteattr(self_url)} rel="self" type="application/rss+xml"/>',
        f"<description>{escape(podcast.description)}</description>",
        f"<language>{escape(podcast.language)}</language>",
        f"<itunes:author>{escape(podcast.author_name)}</itunes:author>",
        f"<itunes:explicit>{'true' if podcast.explicit else 'false'}</itunes:explicit>",
        f"<itunes:category text={quoteattr(podcast.category)}/>",
        f"<podcast:guid>{podcast.pk}</podcast:guid>",
    ]
    if podcast.cover_media_id:
        cover = _abs(reverse("v1:podcast:podcast-cover", kwargs={"podcast_id": podcast.pk}))
        out.append(f"<itunes:image href={quoteattr(cover)}/>")
    for episode in live_episodes(podcast).select_related("season")[:500]:
        media_id = episode.audio_media_id or episode.video_media_id
        ref = library.resolve(media_id) if (library and media_id) else None
        if ref is None:
            continue
        enclosure = _abs(reverse("v1:podcast:episode-stream", kwargs={"episode_id": episode.pk}))
        mime = "audio/mpeg" if "mp3" in ref.variants else ref.mime_type
        out += [
            "<item>",
            f"<title>{escape(episode.title)}</title>",
            f"<description>{escape(episode.show_notes or episode.summary)}</description>",
            f'<guid isPermaLink="false">{episode.pk}</guid>',
            f"<pubDate>{format_datetime(episode.published_at)}</pubDate>",
            f'<enclosure url={quoteattr(enclosure)} length="{ref.size}" type={quoteattr(mime)}/>',
            f"<itunes:duration>{_duration(episode.duration_seconds)}</itunes:duration>",
            f"<itunes:episodeType>{escape(episode.episode_type)}</itunes:episodeType>",
            f"<itunes:explicit>{'true' if episode.explicit else 'false'}</itunes:explicit>",
        ]
        if episode.number:
            out.append(f"<itunes:episode>{episode.number}</itunes:episode>")
        if episode.season_id:
            out.append(f"<itunes:season>{episode.season.number}</itunes:season>")
        if hasattr(episode, "transcript") and episode.transcript.status == "ready" and episode.transcript.cues:
            vtt = _abs(reverse("v1:podcast:episode-transcript-vtt", kwargs={"episode_id": episode.pk}))
            out.append(f'<podcast:transcript url={quoteattr(vtt)} type="text/vtt"/>')
        out.append("</item>")
    out += ["</channel>", "</rss>"]
    return "\n".join(out)
