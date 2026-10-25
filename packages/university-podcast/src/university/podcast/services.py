"""Podcast services: shows, members, seasons, episodes, guests, transcripts, clips, plays.

Media (audio, video, covers, clips) goes through Core's media library: an
episode can only use media its editor uploaded, and can only be published
once the media finished processing. Every mutation authorises with
``podcast.manage`` at the podcast's scope (members hold it implicitly;
host-scope managers inherit it).
"""

from __future__ import annotations

import datetime as dt
import secrets
from collections.abc import Mapping
from typing import Any

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.db.models import F
from django.utils import timezone
from django.utils.text import slugify

from university.audit.services import record as audit
from university.core.content import ensure_can_create
from university.core.crypto import keyed_hash
from university.core.events import publish
from university.core.exceptions import Conflict, NotFound, PermissionDenied, ValidationError
from university.core.hooks import Hook, hooks
from university.core.media import require_media_library
from university.core.providers import get_spam_filter
from university.core.providers.spam import SpamAction
from university.core.ratelimit import rate_limit
from university.core.tasks import enqueue, task
from university.permissions.scopes import Scope
from university.permissions.services import authorize, has_permission
from university.podcast.conf import podcast_settings
from university.podcast.constants import (
    CLIP_MEDIA_PURPOSE,
    COVER_MEDIA_PURPOSE,
    EPISODE_CONTENT_TYPE,
    EPISODE_MEDIA_PURPOSE,
    MEMBER_RANK,
    SHOW_CONTENT_TYPE,
    EpisodeStatus,
    MemberRole,
    ShowStatus,
    ShowVisibility,
    TranscriptStatus,
)
from university.podcast.models import (
    Clip,
    Episode,
    EpisodeDailyStat,
    EpisodeGuest,
    Podcast,
    PodcastMember,
    Season,
    Subscription,
    Transcript,
)
from university.podcast.selectors import can_manage, get_podcast, member_role, podcast_scope

SHOW_FIELDS = ("title", "description", "author_name", "category", "language", "explicit", "website", "visibility")
EPISODE_FIELDS = ("title", "summary", "show_notes", "episode_type", "explicit", "number")


def _screen(text: str, actor: Any) -> None:
    if not text.strip():
        return
    verdict = get_spam_filter().check(text, actor=actor, context={"kind": "podcast"})
    if verdict.action == SpamAction.REJECT:
        raise ValidationError("This content was rejected by our spam filter.", code="content_rejected")


def _manage(actor: Any, podcast: Podcast) -> None:
    authorize(actor, "podcast.manage", podcast_scope(podcast), audit_denial=True)


def _locked_podcast(lookup: Any) -> Podcast:
    return Podcast.objects.select_for_update().get(pk=get_podcast(lookup).pk)


def _validate_show(podcast: Podcast) -> None:
    if podcast.category not in podcast_settings.get("CATEGORIES", []):
        raise ValidationError(details={"category": ["Unknown category."]})
    if podcast.language not in podcast_settings.get("LANGUAGES", []):
        raise ValidationError(details={"language": ["Unsupported language."]})
    if podcast.website and not podcast.website.lower().startswith("https://"):
        raise ValidationError(details={"website": ["Use an https:// link."]})
    if podcast.visibility == ShowVisibility.AUDIENCE and not podcast.scope_type:
        raise ValidationError(details={"visibility": ["Only hosted podcasts can be limited to members."]})


def _media(media_id: str, *, owner: Any, purpose: str, object_id: Any, kinds: tuple[str, ...]) -> Any:
    ref = require_media_library().attach(media_id, owner=owner, purpose=purpose, object_id=object_id)
    if ref.kind not in kinds:
        require_media_library().detach(media_id, purpose=purpose, object_id=object_id)
        raise ValidationError(details={"media": [f"Expected {' or '.join(kinds)}."]}, code="wrong_media_kind")
    return ref


# ------------------------------------------------------------------- shows
@transaction.atomic
def create_podcast(*, owner: Any, data: Mapping[str, Any], scope_type: str = "", scope_id: Any = "") -> Podcast:
    rate_limit("podcast_create", key=str(owner.pk))
    ensure_can_create(owner, SHOW_CONTENT_TYPE)
    scope_id = str(scope_id or "")
    if scope_type or scope_id:
        from university.core.registry import registry

        if not (scope_type and scope_id) or scope_type not in registry.scope_types:
            raise ValidationError(details={"scope_type": ["Unknown host."]})
        authorize(owner, "podcast.manage", Scope(scope_type, scope_id), audit_denial=True)
    elif podcast_settings.get("CREATION_POLICY") == "permission":
        authorize(owner, "podcast.create", audit_denial=True)
    elif not owner.email_verified_at:
        raise PermissionDenied("Verify your email address to start a podcast.", code="email_not_verified")
    if PodcastMember.objects.filter(user=owner, role=MemberRole.OWNER).count() >= int(
        podcast_settings.get("MAX_PODCASTS_PER_USER", 5)
    ):
        raise PermissionDenied("You've reached the podcast limit.", code="podcast_limit_reached")
    fields = {k: v for k, v in data.items() if k in SHOW_FIELDS}
    podcast = Podcast(
        owner=owner,
        scope_type=scope_type,
        scope_id=scope_id,
        slug=f"{slugify(fields.get('title', ''))[:80] or 'podcast'}-{secrets.token_hex(3)}",
        **fields,
    )
    podcast.author_name = podcast.author_name or (owner.display_name or owner.handle or "")[:120]
    _validate_show(podcast)
    _screen(f"{podcast.title}\n{podcast.description}", owner)
    podcast.save()
    PodcastMember.objects.create(podcast=podcast, user=owner, role=MemberRole.OWNER)
    audit("podcast.created", actor=owner, target=podcast, category="podcast")
    return podcast


@transaction.atomic
def update_podcast(
    *, actor: Any, podcast_id: Any, data: Mapping[str, Any], cover_media_id: str | None = None
) -> Podcast:
    podcast = _locked_podcast(podcast_id)
    _manage(actor, podcast)
    for key, value in data.items():
        if key in SHOW_FIELDS:
            setattr(podcast, key, value)
    _validate_show(podcast)
    _screen(f"{podcast.title}\n{podcast.description}", actor)
    if cover_media_id is not None:
        library = require_media_library()
        if podcast.cover_media_id:
            library.detach(podcast.cover_media_id, purpose=COVER_MEDIA_PURPOSE, object_id=podcast.pk)
        if cover_media_id:
            _media(cover_media_id, owner=actor, purpose=COVER_MEDIA_PURPOSE, object_id=podcast.pk, kinds=("image",))
        podcast.cover_media_id = cover_media_id
    podcast.save()
    return podcast


@transaction.atomic
def set_podcast_status(*, actor: Any, podcast_id: Any, action: str) -> Podcast:
    podcast = _locked_podcast(podcast_id)
    _manage(actor, podcast)
    if action == "publish":
        if podcast.hidden_at:
            raise PermissionDenied("This podcast was hidden by the moderators.", code="podcast_hidden")
        podcast.status = ShowStatus.PUBLISHED
        podcast.published_at = podcast.published_at or timezone.now()
    elif action == "archive":
        podcast.status = ShowStatus.ARCHIVED
    else:
        raise ValidationError(details={"action": ["Choose publish or archive."]})
    podcast.save(update_fields=["status", "published_at", "updated_at"])
    audit(f"podcast.{action}", actor=actor, target=podcast, category="podcast")
    return podcast


# ----------------------------------------------------------------- members
def _rank(actor: Any, podcast: Podcast) -> int:
    role = member_role(actor, podcast)
    if role is None and has_permission(actor, "podcast.manage", podcast_scope(podcast)):
        return MEMBER_RANK[MemberRole.OWNER]
    return MEMBER_RANK.get(role, 0)


@transaction.atomic
def add_member(*, actor: Any, podcast_id: Any, user_id: Any, role: str) -> PodcastMember:
    podcast = _locked_podcast(podcast_id)
    _manage(actor, podcast)
    if role not in (MemberRole.HOST, MemberRole.PRODUCER):
        raise ValidationError(details={"role": ["Choose host or producer."]})
    if _rank(actor, podcast) <= MEMBER_RANK[role]:
        raise PermissionDenied("You can only add roles below your own.", code="insufficient_rank")
    user = get_user_model().objects.filter(pk=user_id, is_active=True).first()
    if user is None or not hooks.allows(Hook.USER_CAN_INTERACT, actor, user, "invite"):
        raise NotFound("User not found.")
    if podcast.members.count() >= int(podcast_settings.get("MAX_MEMBERS", 10)):
        raise ValidationError("This podcast has the maximum number of members.", code="member_limit")
    member, created = PodcastMember.objects.get_or_create(podcast=podcast, user=user, defaults={"role": role})
    if not created:
        if member.role == MemberRole.OWNER or _rank(actor, podcast) <= MEMBER_RANK[member.role]:
            raise PermissionDenied("You can't change this person's role.", code="insufficient_rank")
        member.role = role
        member.save(update_fields=["role", "updated_at"])
    audit(
        "podcast.member.added",
        actor=actor,
        target=podcast,
        category="podcast",
        metadata={"user_id": str(user.pk), "role": role},
    )
    return member


@transaction.atomic
def remove_member(*, actor: Any, podcast_id: Any, user_id: Any) -> None:
    podcast = _locked_podcast(podcast_id)
    member = podcast.members.filter(user_id=user_id).first()
    if member is None:
        raise NotFound("Member not found.")
    if member.role == MemberRole.OWNER:
        raise Conflict("Transfer ownership before the owner leaves.", code="owner_must_transfer")
    if member.user_id != actor.pk:
        _manage(actor, podcast)
        if _rank(actor, podcast) <= MEMBER_RANK[member.role]:
            raise PermissionDenied("You can only remove roles below your own.", code="insufficient_rank")
    member.delete()


@transaction.atomic
def transfer_ownership(*, actor: Any, podcast_id: Any, user_id: Any) -> None:
    podcast = _locked_podcast(podcast_id)
    if _rank(actor, podcast) < MEMBER_RANK[MemberRole.OWNER]:
        raise PermissionDenied("Only the owner can transfer ownership.", code="insufficient_rank")
    target = podcast.members.filter(user_id=user_id).exclude(role=MemberRole.OWNER).first()
    if target is None:
        raise ValidationError("The new owner must already be a member.", code="not_a_member")
    podcast.members.filter(role=MemberRole.OWNER).update(role=MemberRole.HOST)
    target.role = MemberRole.OWNER
    target.save(update_fields=["role", "updated_at"])
    podcast.owner_id = target.user_id
    podcast.save(update_fields=["owner", "updated_at"])


# ----------------------------------------------------------------- seasons
@transaction.atomic
def create_season(*, actor: Any, podcast_id: Any, number: int, title: str = "", description: str = "") -> Season:
    podcast = _locked_podcast(podcast_id)
    _manage(actor, podcast)
    try:
        with transaction.atomic():
            return Season.objects.create(
                podcast=podcast, number=number, title=title[:160], description=description[:5000]
            )
    except IntegrityError:
        raise Conflict("That season already exists.", code="season_exists") from None


# ---------------------------------------------------------------- episodes
def _locked_episode(episode_id: Any) -> Episode:
    episode = Episode.objects.select_for_update().select_related("podcast").filter(pk=episode_id).first()
    if episode is None:
        raise NotFound("Episode not found.")
    return episode


def _set_media(actor: Any, episode: Episode, field: str, media_id: str | None, kinds: tuple[str, ...]) -> None:
    if media_id is None:
        return
    library = require_media_library()
    old = getattr(episode, field)
    if old == media_id:
        return
    if old:
        library.detach(old, purpose=EPISODE_MEDIA_PURPOSE, object_id=episode.pk)
    if media_id:
        ref = _media(media_id, owner=actor, purpose=EPISODE_MEDIA_PURPOSE, object_id=episode.pk, kinds=kinds)
        if ref.duration_seconds:
            episode.duration_seconds = ref.duration_seconds
    setattr(episode, field, media_id)


def _season(podcast: Podcast, season_id: Any) -> Season | None:
    if not season_id:
        return None
    season = Season.objects.filter(pk=season_id, podcast=podcast).first()
    if season is None:
        raise ValidationError(details={"season": ["Season not found."]})
    return season


@transaction.atomic
def create_episode(
    *,
    actor: Any,
    podcast_id: Any,
    data: Mapping[str, Any],
    audio_media_id: str = "",
    video_media_id: str = "",
    season_id: Any = None,
) -> Episode:
    podcast = _locked_podcast(podcast_id)
    _manage(actor, podcast)
    ensure_can_create(actor, EPISODE_CONTENT_TYPE)
    fields = {k: v for k, v in data.items() if k in EPISODE_FIELDS}
    episode = Episode(
        podcast=podcast,
        season=_season(podcast, season_id),
        created_by=actor,
        slug=f"{slugify(fields.get('title', ''))[:80] or 'episode'}-{secrets.token_hex(3)}",
        **fields,
    )
    _screen(f"{episode.title}\n{episode.summary}\n{episode.show_notes}", actor)
    episode.save()
    _set_media(actor, episode, "audio_media_id", audio_media_id or None, ("audio",))
    _set_media(actor, episode, "video_media_id", video_media_id or None, ("video",))
    episode.save()
    return episode


@transaction.atomic
def update_episode(
    *,
    actor: Any,
    episode_id: Any,
    data: Mapping[str, Any],
    audio_media_id: str | None = None,
    video_media_id: str | None = None,
    season_id: Any = ...,
) -> Episode:
    episode = _locked_episode(episode_id)
    _manage(actor, episode.podcast)
    for key, value in data.items():
        if key in EPISODE_FIELDS:
            setattr(episode, key, value)
    if season_id is not ...:
        episode.season = _season(episode.podcast, season_id)
    _set_media(actor, episode, "audio_media_id", audio_media_id, ("audio",))
    _set_media(actor, episode, "video_media_id", video_media_id, ("video",))
    _screen(f"{episode.title}\n{episode.summary}\n{episode.show_notes}", actor)
    episode.save()
    return episode


def _require_ready_media(episode: Episode) -> None:
    library = require_media_library()
    ids = [m for m in (episode.audio_media_id, episode.video_media_id) if m]
    if not ids:
        raise ValidationError("Add audio or video first.", code="media_required")
    for media_id in ids:
        ref = library.resolve(media_id)
        if ref is None or not ref.is_ready:
            raise Conflict("The media is still processing.", code="media_not_ready")
        if ref.duration_seconds and not episode.duration_seconds:
            episode.duration_seconds = ref.duration_seconds


def _go_live(episode: Episode) -> None:
    episode.status = EpisodeStatus.PUBLISHED
    episode.published_at = episode.published_at or timezone.now()
    episode.save(update_fields=["status", "published_at", "duration_seconds", "updated_at"])
    payload = {"episode_id": episode.pk, "podcast_id": episode.podcast_id}
    publish("podcast.episode.published", payload)
    enqueue(notify_subscribers, str(episode.pk))


@transaction.atomic
def publish_episode(*, actor: Any, episode_id: Any, publish_at: dt.datetime | None = None) -> Episode:
    episode = _locked_episode(episode_id)
    _manage(actor, episode.podcast)
    if episode.hidden_at:
        raise PermissionDenied("This episode was hidden by the moderators.", code="episode_hidden")
    _require_ready_media(episode)
    if publish_at and publish_at > timezone.now():
        episode.status = EpisodeStatus.SCHEDULED
        episode.publish_at = publish_at
        episode.save(update_fields=["status", "publish_at", "duration_seconds", "updated_at"])
    else:
        _go_live(episode)
    audit("podcast.episode.published", actor=actor, target=episode, category="podcast")
    return episode


@transaction.atomic
def unpublish_episode(*, actor: Any, episode_id: Any) -> Episode:
    episode = _locked_episode(episode_id)
    _manage(actor, episode.podcast)
    episode.status = EpisodeStatus.UNPUBLISHED
    episode.save(update_fields=["status", "updated_at"])
    return episode


def delete_episode_records(episode: Episode) -> None:
    library = require_media_library()
    for media_id in (episode.audio_media_id, episode.video_media_id):
        if media_id:
            library.detach(media_id, purpose=EPISODE_MEDIA_PURPOSE, object_id=episode.pk)
    for clip in episode.clips.all():
        library.detach(clip.media_id, purpose=CLIP_MEDIA_PURPOSE, object_id=clip.pk)
    episode.delete()


@transaction.atomic
def delete_episode(*, actor: Any, episode_id: Any) -> None:
    episode = _locked_episode(episode_id)
    _manage(actor, episode.podcast)
    delete_episode_records(episode)


@task(name="university.podcast.publish_due_episodes")
def publish_due_episodes() -> int:
    published = 0
    for episode_id in list(
        Episode.objects.filter(status=EpisodeStatus.SCHEDULED, publish_at__lte=timezone.now()).values_list(
            "pk", flat=True
        )
    ):
        with transaction.atomic():
            episode = _locked_episode(episode_id)
            if episode.status == EpisodeStatus.SCHEDULED and episode.hidden_at is None:
                episode.published_at = episode.publish_at
                _go_live(episode)
                published += 1
    return published


@task(name="university.podcast.notify_subscribers")
def notify_subscribers(episode_id: str) -> int:
    episode = Episode.objects.filter(pk=episode_id).first()
    if episode is None:
        return 0
    count = 0
    for user_id in (
        Subscription.objects.filter(podcast_id=episode.podcast_id).values_list("user_id", flat=True).iterator()
    ):
        publish(
            "podcast.subscriber.notice",
            {"user_id": user_id, "episode_id": episode.pk, "podcast_id": episode.podcast_id},
        )
        count += 1
    return count


# ------------------------------------------------------------------ guests
@transaction.atomic
def add_guest(*, actor: Any, episode_id: Any, name: str, bio: str = "", user_id: Any = None) -> EpisodeGuest:
    episode = _locked_episode(episode_id)
    _manage(actor, episode.podcast)
    if episode.guests.count() >= int(podcast_settings.get("MAX_GUESTS_PER_EPISODE", 10)):
        raise ValidationError("This episode has the maximum number of guests.", code="guest_limit")
    user = None
    if user_id:
        user = get_user_model().objects.filter(pk=user_id, is_active=True).first()
        if user is None or not hooks.allows(Hook.USER_CAN_INTERACT, actor, user, "invite"):
            raise NotFound("User not found.")
    guest = EpisodeGuest.objects.create(
        episode=episode, name=name.strip()[:120], bio=bio[:300], user=user, position=episode.guests.count()
    )
    if user is not None:
        publish(
            "podcast.guest.added",
            {"guest_id": guest.pk, "user_id": user.pk, "episode_id": episode.pk, "podcast_id": episode.podcast_id},
        )
    return guest


@transaction.atomic
def respond_to_guest_spot(*, user: Any, guest_id: Any, accept: bool) -> EpisodeGuest | None:
    guest = EpisodeGuest.objects.select_for_update().filter(pk=guest_id, user=user).first()
    if guest is None:
        raise NotFound("Guest spot not found.")
    if accept:
        guest.confirmed_at = timezone.now()
        guest.save(update_fields=["confirmed_at", "updated_at"])
        return guest
    guest.user = None  # Declining unlinks the account; the name stays as typed by the hosts.
    guest.confirmed_at = None
    guest.save(update_fields=["user", "confirmed_at", "updated_at"])
    return None


@transaction.atomic
def remove_guest(*, actor: Any, episode_id: Any, guest_id: Any) -> None:
    episode = _locked_episode(episode_id)
    _manage(actor, episode.podcast)
    if not episode.guests.filter(pk=guest_id).delete()[0]:
        raise NotFound("Guest not found.")


# ------------------------------------------------------------- transcripts
@transaction.atomic
def set_transcript(
    *, actor: Any, episode_id: Any, content: str, source_format: str, language: str = "en"
) -> Transcript:
    from university.podcast.transcripts import parse

    episode = _locked_episode(episode_id)
    _manage(actor, episode.podcast)
    if len(content.encode("utf-8")) > int(podcast_settings.get("TRANSCRIPT_MAX_BYTES", 2 * 1024 * 1024)):
        raise ValidationError(details={"content": ["The transcript is too large."]})
    cues, text = parse(content, source_format)
    transcript, _ = Transcript.objects.update_or_create(
        episode=episode,
        defaults={
            "language": language[:8],
            "source_format": source_format,
            "text": text,
            "cues": cues,
            "status": TranscriptStatus.READY,
            "automatic": False,
            "error": "",
        },
    )
    return transcript


@transaction.atomic
def request_transcription(*, actor: Any, episode_id: Any, language: str = "en") -> Transcript:
    from university.podcast.transcription import get_transcription_provider

    episode = _locked_episode(episode_id)
    _manage(actor, episode.podcast)
    if get_transcription_provider() is None:
        raise Conflict("Automatic transcription isn't enabled.", code="transcription_unavailable")
    if not episode.audio_media_id:
        raise ValidationError("Add audio first.", code="media_required")
    transcript, _ = Transcript.objects.update_or_create(
        episode=episode,
        defaults={"language": language[:8], "status": TranscriptStatus.PENDING, "automatic": True, "error": ""},
    )
    transaction.on_commit(lambda: enqueue(transcribe_episode, str(episode.pk)))
    return transcript


@task(name="university.podcast.transcribe_episode")
def transcribe_episode(episode_id: str) -> None:
    from university.podcast.transcription import get_transcription_provider

    transcript = Transcript.objects.select_related("episode").filter(episode_id=episode_id).first()
    provider = get_transcription_provider()
    if transcript is None or provider is None or transcript.status != TranscriptStatus.PENDING:
        return
    try:
        url = require_media_library().url(transcript.episode.audio_media_id, variant="mp3", ttl_seconds=6 * 3600)
        cues = provider.transcribe(audio_url=url, language=transcript.language)
        clean = [
            {"start": float(c["start"]), "end": float(c["end"]), "text": str(c["text"])[:2000]}
            for c in cues
            if str(c.get("text", "")).strip()
        ]
        transcript.cues = clean
        transcript.text = "\n".join(c["text"] for c in clean)
        transcript.status = TranscriptStatus.READY
        transcript.error = ""
    except Exception as exc:
        transcript.status = TranscriptStatus.FAILED
        transcript.error = str(getattr(exc, "code", type(exc).__name__))[:64]
    transcript.save()


# ------------------------------------------------------------------- clips
@transaction.atomic
def create_clip(*, actor: Any, episode_id: Any, title: str, start: float, end: float) -> Clip:
    episode = _locked_episode(episode_id)
    _manage(actor, episode.podcast)
    media_id = episode.video_media_id or episode.audio_media_id
    if not media_id:
        raise ValidationError("Add audio or video first.", code="media_required")
    library = require_media_library()
    ref = library.resolve(media_id)
    owner = get_user_model().objects.filter(pk=ref.owner_id).first() if ref and ref.owner_id else None
    if owner is None:
        raise Conflict("The episode's media owner left; re-upload the media to make clips.", code="media_orphaned")
    clip_ref = library.create_clip(media_id, owner=owner, start_seconds=start, end_seconds=end)
    clip = Clip.objects.create(
        episode=episode,
        title=title.strip()[:160],
        start_seconds=start,
        end_seconds=end,
        media_id=clip_ref.id,
        created_by=actor,
    )
    library.attach(clip_ref.id, owner=owner, purpose=CLIP_MEDIA_PURPOSE, object_id=clip.pk)
    return clip


@transaction.atomic
def delete_clip(*, actor: Any, clip_id: Any) -> None:
    clip = Clip.objects.select_related("episode__podcast").filter(pk=clip_id).first()
    if clip is None:
        raise NotFound("Clip not found.")
    _manage(actor, clip.episode.podcast)
    require_media_library().detach(clip.media_id, purpose=CLIP_MEDIA_PURPOSE, object_id=clip.pk)
    clip.delete()


# ----------------------------------------------------------- subscriptions
@transaction.atomic
def subscribe(*, user: Any, podcast_id: Any) -> Subscription:
    podcast = _locked_podcast(podcast_id)
    sub, created = Subscription.objects.get_or_create(podcast=podcast, user=user)
    if created:
        Podcast.objects.filter(pk=podcast.pk).update(subscriber_count=F("subscriber_count") + 1)
    return sub


@transaction.atomic
def unsubscribe(*, user: Any, podcast_id: Any) -> None:
    podcast = _locked_podcast(podcast_id)
    if Subscription.objects.filter(podcast=podcast, user=user).delete()[0]:
        Podcast.objects.filter(pk=podcast.pk, subscriber_count__gt=0).update(subscriber_count=F("subscriber_count") - 1)


# ------------------------------------------------------------------- plays
def _bump(episode: Episode, field: str) -> None:
    day = timezone.localdate()
    if not EpisodeDailyStat.objects.filter(episode=episode, date=day).update(**{field: F(field) + 1}):
        try:
            with transaction.atomic():
                EpisodeDailyStat.objects.create(episode=episode, date=day, **{field: 1})
        except IntegrityError:
            EpisodeDailyStat.objects.filter(episode=episode, date=day).update(**{field: F(field) + 1})


def record_play(*, episode: Episode, listener: Any, fingerprint: str, position_seconds: float) -> dict[str, bool]:
    """Count a play and a completion at most once per listener per window; store no listener data."""
    who = f"u:{listener.pk}" if getattr(listener, "is_authenticated", False) else f"a:{fingerprint}"
    window = int(podcast_settings.get("PLAY_DEDUPE_HOURS", 24)) * 3600
    counted = {"play": False, "completion": False}
    base = keyed_hash(f"{episode.pk}:{who}", purpose="podcast.play_dedupe")[:32]
    if cache.add(f"podcast:play:{base}", 1, timeout=window):
        _bump(episode, "plays")
        counted["play"] = True
    threshold = float(podcast_settings.get("COMPLETION_THRESHOLD", 0.9))
    finished = bool(episode.duration_seconds and position_seconds >= threshold * episode.duration_seconds)
    if finished and cache.add(f"podcast:done:{base}", 1, timeout=window):
        _bump(episode, "completions")
        counted["completion"] = True
    return counted


def analytics(*, actor: Any, podcast_id: Any, start: dt.date, end: dt.date) -> dict[str, Any]:
    from django.db.models import Sum

    podcast = get_podcast(podcast_id)
    if not can_manage(actor, podcast):
        raise PermissionDenied()
    if end < start or (end - start).days > 366:
        raise ValidationError(details={"from": ["Choose a range of up to a year."]})
    rows = EpisodeDailyStat.objects.filter(episode__podcast=podcast, date__range=(start, end))
    per_episode = rows.values("episode_id", "episode__title").annotate(
        plays=Sum("plays"), completions=Sum("completions")
    )
    daily = rows.values("date").annotate(plays=Sum("plays"), completions=Sum("completions")).order_by("date")
    return {
        "from": start.isoformat(),
        "to": end.isoformat(),
        "subscribers": podcast.subscriber_count,
        "episodes": [
            {
                "episode_id": r["episode_id"],
                "title": r["episode__title"],
                "plays": r["plays"],
                "completions": r["completions"],
            }
            for r in per_episode.order_by("-plays")
        ],
        "daily": [{"date": r["date"].isoformat(), "plays": r["plays"], "completions": r["completions"]} for r in daily],
    }
