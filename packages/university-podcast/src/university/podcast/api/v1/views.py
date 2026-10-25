from __future__ import annotations

import datetime as dt
from typing import Any

from django.http import HttpResponse, HttpResponseRedirect
from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from university.core.api.pagination import PageNumberPagination
from university.core.api.schema import OpenApiParameter, OpenApiTypes, extend_schema
from university.core.context import get_request_context
from university.core.exceptions import AuthenticationFailed, NotFound, ValidationError
from university.core.media import require_media_library
from university.podcast import selectors, services
from university.podcast.api.v1 import serializers as s
from university.podcast.constants import ShowStatus, ShowVisibility
from university.podcast.models import Clip, Episode, Podcast, PodcastMember, Subscription, Transcript
from university.podcast.rss import build_feed
from university.podcast.transcripts import to_vtt


def _user(request: Request) -> Any:
    if not request.user.is_authenticated:
        raise AuthenticationFailed()
    return request.user


def _show_context(request: Request, podcasts: list[Any]) -> dict[str, Any]:
    ids = [p.pk for p in podcasts]
    if not request.user.is_authenticated or not ids:
        return {}
    return {
        "subscribed": set(
            Subscription.objects.filter(user=request.user, podcast_id__in=ids).values_list("podcast_id", flat=True)
        ),
        "roles": dict(
            PodcastMember.objects.filter(user=request.user, podcast_id__in=ids).values_list("podcast_id", "role")
        ),
    }


def _show(request: Request, podcast: Any) -> dict[str, Any]:
    return s.PodcastShowSerializer(podcast, context=_show_context(request, [podcast])).data


def _paginate(
    view: APIView, request: Request, qs: Any, serializer: Any, context: dict[str, Any] | None = None
) -> Response:
    paginator = PageNumberPagination()
    page = paginator.paginate_queryset(qs, request, view=view)
    ctx = context(request, page) if callable(context) else (context or {})
    return paginator.get_paginated_response(serializer(page, many=True, context=ctx).data)


def _redirect(url: str) -> HttpResponse:
    response = HttpResponseRedirect(url)
    response["Cache-Control"] = "private, no-store"
    return response


# ------------------------------------------------------------------- shows
class PodcastListCreateView(APIView):
    permission_classes = [permissions.AllowAny]

    @extend_schema(
        parameters=[OpenApiParameter(p, str) for p in ("q", "category", "language", "scope_type", "scope_id")],
        responses=s.PodcastShowSerializer(many=True),
    )
    def get(self, request: Request) -> Response:
        return _paginate(
            self,
            request,
            selectors.discover(request.user, request.query_params),
            s.PodcastShowSerializer,
            _show_context,
        )

    @extend_schema(request=s.PodcastShowWriteSerializer, responses={201: s.PodcastShowSerializer})
    def post(self, request: Request) -> Response:
        user = _user(request)
        serializer = s.PodcastShowWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        host_type, host_id = data.pop("host_type"), data.pop("host_id")
        cover = data.pop("cover_media_id", None)
        podcast = services.create_podcast(owner=user, data=data, scope_type=host_type, scope_id=host_id)
        if cover:
            podcast = services.update_podcast(actor=user, podcast_id=podcast.pk, data={}, cover_media_id=cover)
        return Response(_show(request, podcast), status=status.HTTP_201_CREATED)


class PodcastDetailView(APIView):
    permission_classes = [permissions.AllowAny]

    @extend_schema(responses=s.PodcastShowSerializer)
    def get(self, request: Request, podcast_id: Any) -> Response:
        return Response(_show(request, selectors.get_visible_podcast(request.user, podcast_id)))

    @extend_schema(request=s.PodcastShowWriteSerializer, responses=s.PodcastShowSerializer)
    def patch(self, request: Request, podcast_id: Any) -> Response:
        user = _user(request)
        selectors.get_visible_podcast(user, podcast_id)
        serializer = s.PodcastShowWriteSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        data = {k: v for k, v in serializer.validated_data.items() if k not in ("host_type", "host_id")}
        cover = data.pop("cover_media_id", None)
        return Response(
            _show(request, services.update_podcast(actor=user, podcast_id=podcast_id, data=data, cover_media_id=cover))
        )


class PodcastBySlugView(APIView):
    permission_classes = [permissions.AllowAny]

    @extend_schema(responses=s.PodcastShowSerializer)
    def get(self, request: Request, slug: str) -> Response:
        return Response(_show(request, selectors.get_visible_podcast(request.user, slug)))


class PodcastStatusView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(request=s.PodcastActionSerializer, responses=s.PodcastShowSerializer)
    def post(self, request: Request, podcast_id: Any) -> Response:
        selectors.get_visible_podcast(request.user, podcast_id)
        serializer = s.PodcastActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(
            _show(
                request,
                services.set_podcast_status(actor=request.user, podcast_id=podcast_id, **serializer.validated_data),
            )
        )


class PodcastCoverView(APIView):
    permission_classes = [permissions.AllowAny]

    @extend_schema(responses={302: None})
    def get(self, request: Request, podcast_id: Any) -> HttpResponse:
        podcast = selectors.get_visible_podcast(request.user, podcast_id)
        if not podcast.cover_media_id:
            raise NotFound("No cover.")
        return _redirect(require_media_library().url(podcast.cover_media_id))


class PodcastFeedView(APIView):
    permission_classes = [permissions.AllowAny]

    @extend_schema(responses={(200, "application/rss+xml"): OpenApiTypes.STR})
    def get(self, request: Request, slug: str) -> HttpResponse:
        podcast = Podcast.objects.filter(
            slug=slug,
            status=ShowStatus.PUBLISHED,
            hidden_at__isnull=True,
            visibility__in=[ShowVisibility.PUBLIC, ShowVisibility.UNLISTED],
        ).first()
        if podcast is None:
            raise NotFound("Feed not found.")
        response = HttpResponse(build_feed(podcast), content_type="application/rss+xml; charset=utf-8")
        response["Cache-Control"] = "public, max-age=300"
        return response


class PodcastMembersView(APIView):
    permission_classes = [permissions.AllowAny]

    @extend_schema(responses=s.PodcastMemberSerializer(many=True))
    def get(self, request: Request, podcast_id: Any) -> Response:
        podcast = selectors.get_visible_podcast(request.user, podcast_id)
        return Response(
            s.PodcastMemberSerializer(podcast.members.select_related("user").order_by("created_at"), many=True).data
        )

    @extend_schema(request=s.PodcastMemberWriteSerializer, responses={201: s.PodcastMemberSerializer})
    def post(self, request: Request, podcast_id: Any) -> Response:
        user = _user(request)
        selectors.get_visible_podcast(user, podcast_id)
        serializer = s.PodcastMemberWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        member = services.add_member(actor=user, podcast_id=podcast_id, **serializer.validated_data)
        return Response(s.PodcastMemberSerializer(member).data, status=status.HTTP_201_CREATED)


class PodcastMemberDetailView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(responses={204: None})
    def delete(self, request: Request, podcast_id: Any, user_id: Any) -> Response:
        services.remove_member(actor=request.user, podcast_id=podcast_id, user_id=user_id)
        return Response(status=status.HTTP_204_NO_CONTENT)


class PodcastTransferView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(request=s.PodcastUserRefSerializer, responses={204: None})
    def post(self, request: Request, podcast_id: Any) -> Response:
        serializer = s.PodcastUserRefSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.transfer_ownership(actor=request.user, podcast_id=podcast_id, **serializer.validated_data)
        return Response(status=status.HTTP_204_NO_CONTENT)


class PodcastSeasonsView(APIView):
    permission_classes = [permissions.AllowAny]

    @extend_schema(responses=s.PodcastSeasonSerializer(many=True))
    def get(self, request: Request, podcast_id: Any) -> Response:
        return Response(
            s.PodcastSeasonSerializer(
                selectors.get_visible_podcast(request.user, podcast_id).seasons.all(), many=True
            ).data
        )

    @extend_schema(request=s.PodcastSeasonWriteSerializer, responses={201: s.PodcastSeasonSerializer})
    def post(self, request: Request, podcast_id: Any) -> Response:
        user = _user(request)
        serializer = s.PodcastSeasonWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        season = services.create_season(actor=user, podcast_id=podcast_id, **serializer.validated_data)
        return Response(s.PodcastSeasonSerializer(season).data, status=status.HTTP_201_CREATED)


class PodcastEpisodesView(APIView):
    permission_classes = [permissions.AllowAny]

    @extend_schema(responses=s.PodcastEpisodeSerializer(many=True))
    def get(self, request: Request, podcast_id: Any) -> Response:
        podcast = selectors.get_visible_podcast(request.user, podcast_id)
        if selectors.can_manage(request.user, podcast):
            qs = Episode.objects.filter(podcast=podcast).order_by("-created_at")
        else:
            qs = selectors.live_episodes(podcast)
        return _paginate(
            self, request, qs.select_related("season").prefetch_related("guests"), s.PodcastEpisodeSerializer
        )

    @extend_schema(request=s.PodcastEpisodeWriteSerializer, responses={201: s.PodcastEpisodeSerializer})
    def post(self, request: Request, podcast_id: Any) -> Response:
        user = _user(request)
        selectors.get_visible_podcast(user, podcast_id)
        serializer = s.PodcastEpisodeWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        episode = services.create_episode(
            actor=user,
            podcast_id=podcast_id,
            audio_media_id=data.pop("audio_media_id", ""),
            video_media_id=data.pop("video_media_id", ""),
            season_id=data.pop("season", None),
            data=data,
        )
        return Response(s.PodcastEpisodeSerializer(episode).data, status=status.HTTP_201_CREATED)


class PodcastSubscribeView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(request=None, responses={204: None})
    def post(self, request: Request, podcast_id: Any) -> Response:
        selectors.get_visible_podcast(request.user, podcast_id)
        services.subscribe(user=request.user, podcast_id=podcast_id)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(responses={204: None})
    def delete(self, request: Request, podcast_id: Any) -> Response:
        services.unsubscribe(user=request.user, podcast_id=podcast_id)
        return Response(status=status.HTTP_204_NO_CONTENT)


class PodcastAnalyticsView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        parameters=[OpenApiParameter("from", str), OpenApiParameter("to", str)], responses=OpenApiTypes.OBJECT
    )
    def get(self, request: Request, podcast_id: Any) -> Response:
        try:
            end = (
                dt.date.fromisoformat(request.query_params["to"])
                if request.query_params.get("to")
                else timezone.localdate()
            )
            start = (
                dt.date.fromisoformat(request.query_params["from"])
                if request.query_params.get("from")
                else end - dt.timedelta(days=29)
            )
        except ValueError:
            raise ValidationError(details={"from": ["Use YYYY-MM-DD."]}) from None
        return Response(services.analytics(actor=request.user, podcast_id=podcast_id, start=start, end=end))


# ---------------------------------------------------------------- episodes
class EpisodeDetailView(APIView):
    permission_classes = [permissions.AllowAny]

    @extend_schema(responses=s.PodcastEpisodeSerializer)
    def get(self, request: Request, episode_id: Any) -> Response:
        return Response(s.PodcastEpisodeSerializer(selectors.get_visible_episode(request.user, episode_id)).data)

    @extend_schema(request=s.PodcastEpisodeWriteSerializer, responses=s.PodcastEpisodeSerializer)
    def patch(self, request: Request, episode_id: Any) -> Response:
        user = _user(request)
        selectors.get_visible_episode(user, episode_id)
        serializer = s.PodcastEpisodeWriteSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        kwargs: dict[str, Any] = {
            "audio_media_id": data.pop("audio_media_id", None),
            "video_media_id": data.pop("video_media_id", None),
        }
        if "season" in data:
            kwargs["season_id"] = data.pop("season")
        episode = services.update_episode(actor=user, episode_id=episode_id, data=data, **kwargs)
        return Response(s.PodcastEpisodeSerializer(episode).data)

    @extend_schema(responses={204: None})
    def delete(self, request: Request, episode_id: Any) -> Response:
        user = _user(request)
        selectors.get_visible_episode(user, episode_id)
        services.delete_episode(actor=user, episode_id=episode_id)
        return Response(status=status.HTTP_204_NO_CONTENT)


class EpisodePublishView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    unpublish = False

    @extend_schema(request=s.PodcastPublishSerializer, responses=s.PodcastEpisodeSerializer)
    def post(self, request: Request, episode_id: Any) -> Response:
        selectors.get_visible_episode(request.user, episode_id)
        if self.unpublish:
            return Response(
                s.PodcastEpisodeSerializer(services.unpublish_episode(actor=request.user, episode_id=episode_id)).data
            )
        serializer = s.PodcastPublishSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        episode = services.publish_episode(
            actor=request.user, episode_id=episode_id, publish_at=serializer.validated_data.get("publish_at")
        )
        return Response(s.PodcastEpisodeSerializer(episode).data)


class EpisodeStreamView(APIView):
    """Stable link (RSS enclosures, players) that redirects to a fresh short-lived media URL."""

    permission_classes = [permissions.AllowAny]

    @extend_schema(parameters=[OpenApiParameter("format", str, enum=["audio", "video"])], responses={302: None})
    def get(self, request: Request, episode_id: Any) -> HttpResponse:
        episode = selectors.get_visible_episode(request.user, episode_id)
        library = require_media_library()
        if request.query_params.get("format") == "video" and episode.video_media_id:
            return _redirect(library.url(episode.video_media_id, variant="mp4_720p"))
        media_id = episode.audio_media_id or episode.video_media_id
        if not media_id:
            raise NotFound("No media.")
        return _redirect(library.url(media_id, variant="mp3"))


class EpisodePlayView(APIView):
    permission_classes = [permissions.AllowAny]

    @extend_schema(request=s.PodcastPlaySerializer, responses=s.PodcastPlayResultSerializer)
    def post(self, request: Request, episode_id: Any) -> Response:
        episode = selectors.get_visible_episode(request.user, episode_id)
        serializer = s.PodcastPlaySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        ctx = get_request_context()
        counted = services.record_play(
            episode=episode,
            listener=request.user,
            fingerprint=f"{ctx.ip_address or ''}|{ctx.user_agent[:200]}",
            position_seconds=serializer.validated_data["position_seconds"],
        )
        return Response(counted)


class EpisodeGuestsView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(request=s.PodcastGuestWriteSerializer, responses={201: s.PodcastGuestSerializer})
    def post(self, request: Request, episode_id: Any) -> Response:
        selectors.get_visible_episode(request.user, episode_id)
        serializer = s.PodcastGuestWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        guest = services.add_guest(actor=request.user, episode_id=episode_id, **serializer.validated_data)
        return Response(s.PodcastGuestSerializer(guest).data, status=status.HTTP_201_CREATED)


class EpisodeGuestDetailView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(responses={204: None})
    def delete(self, request: Request, episode_id: Any, guest_id: Any) -> Response:
        services.remove_guest(actor=request.user, episode_id=episode_id, guest_id=guest_id)
        return Response(status=status.HTTP_204_NO_CONTENT)


class GuestResponseView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(request=s.PodcastGuestResponseSerializer, responses={204: None})
    def post(self, request: Request, guest_id: Any) -> Response:
        serializer = s.PodcastGuestResponseSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.respond_to_guest_spot(user=request.user, guest_id=guest_id, accept=serializer.validated_data["accept"])
        return Response(status=status.HTTP_204_NO_CONTENT)


class EpisodeTranscriptView(APIView):
    permission_classes = [permissions.AllowAny]

    @extend_schema(responses=s.PodcastTranscriptSerializer)
    def get(self, request: Request, episode_id: Any) -> Response:
        episode = selectors.get_visible_episode(request.user, episode_id)
        transcript = Transcript.objects.filter(episode=episode).first()
        if transcript is None or (
            transcript.status != "ready" and not selectors.can_manage(request.user, episode.podcast)
        ):
            raise NotFound("No transcript.")
        return Response(s.PodcastTranscriptSerializer(transcript).data)

    @extend_schema(request=s.PodcastTranscriptWriteSerializer, responses=s.PodcastTranscriptSerializer)
    def put(self, request: Request, episode_id: Any) -> Response:
        user = _user(request)
        selectors.get_visible_episode(user, episode_id)
        serializer = s.PodcastTranscriptWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        transcript = services.set_transcript(
            actor=user,
            episode_id=episode_id,
            content=data["content"],
            source_format=data["format"],
            language=data["language"],
        )
        return Response(s.PodcastTranscriptSerializer(transcript).data)


class EpisodeTranscriptVttView(APIView):
    permission_classes = [permissions.AllowAny]

    @extend_schema(responses={(200, "text/vtt"): OpenApiTypes.STR})
    def get(self, request: Request, episode_id: Any) -> HttpResponse:
        episode = selectors.get_visible_episode(request.user, episode_id)
        transcript = Transcript.objects.filter(episode=episode, status="ready").first()
        if transcript is None:
            raise NotFound("No transcript.")
        return HttpResponse(to_vtt(transcript.cues, transcript.text), content_type="text/vtt; charset=utf-8")


class EpisodeTranscribeView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(request=s.PodcastLanguageSerializer, responses={202: s.PodcastTranscriptSerializer})
    def post(self, request: Request, episode_id: Any) -> Response:
        selectors.get_visible_episode(request.user, episode_id)
        serializer = s.PodcastLanguageSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        transcript = services.request_transcription(
            actor=request.user, episode_id=episode_id, **serializer.validated_data
        )
        transcript.refresh_from_db()
        return Response(s.PodcastTranscriptSerializer(transcript).data, status=status.HTTP_202_ACCEPTED)


class EpisodeClipsView(APIView):
    permission_classes = [permissions.AllowAny]

    @extend_schema(responses=s.PodcastClipSerializer(many=True))
    def get(self, request: Request, episode_id: Any) -> Response:
        episode = selectors.get_visible_episode(request.user, episode_id)
        library = require_media_library()
        clips = [
            c for c in episode.clips.order_by("start_seconds") if (ref := library.resolve(c.media_id)) and ref.is_ready
        ]
        return Response(s.PodcastClipSerializer(clips, many=True).data)

    @extend_schema(request=s.PodcastClipWriteSerializer, responses={201: s.PodcastClipSerializer})
    def post(self, request: Request, episode_id: Any) -> Response:
        user = _user(request)
        selectors.get_visible_episode(user, episode_id)
        serializer = s.PodcastClipWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        clip = services.create_clip(
            actor=user, episode_id=episode_id, title=data["title"], start=data["start_seconds"], end=data["end_seconds"]
        )
        return Response(s.PodcastClipSerializer(clip).data, status=status.HTTP_201_CREATED)


class ClipDetailView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(responses={204: None})
    def delete(self, request: Request, clip_id: Any) -> Response:
        services.delete_clip(actor=request.user, clip_id=clip_id)
        return Response(status=status.HTTP_204_NO_CONTENT)


class ClipStreamView(APIView):
    permission_classes = [permissions.AllowAny]

    @extend_schema(responses={302: None})
    def get(self, request: Request, clip_id: Any) -> HttpResponse:
        clip = Clip.objects.select_related("episode__podcast").filter(pk=clip_id).first()
        if clip is None or not selectors.can_view_episode(request.user, clip.episode):
            raise NotFound("Clip not found.")
        return _redirect(require_media_library().url(clip.media_id, variant="mp3"))


# --------------------------------------------------------------------- me
class MySubscriptionsView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(responses=s.PodcastShowSerializer(many=True))
    def get(self, request: Request) -> Response:
        qs = Podcast.objects.filter(subscriptions__user=request.user, hidden_at__isnull=True).order_by("title")
        return _paginate(self, request, qs, s.PodcastShowSerializer, _show_context)


class MyPodcastsView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(responses=s.PodcastShowSerializer(many=True))
    def get(self, request: Request) -> Response:
        qs = Podcast.objects.filter(members__user=request.user).order_by("-created_at")
        return _paginate(self, request, qs, s.PodcastShowSerializer, _show_context)
