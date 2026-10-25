"""Media processors: probe, transcode and clip — always on the task backend.

* :class:`BasicProcessor` (default) needs no external tools: image dimensions
  (Pillow, when installed) and WAV duration and clipping (standard library).
* :class:`FFmpegProcessor` uses ``ffprobe``/``ffmpeg``: probes duration and
  dimensions, makes an MP3 rendition of audio (and of a video's soundtrack),
  a 720p MP4 and a poster frame for video, and cuts clips.

Security: tools run with argument lists (never a shell), ``-nostdin``, a
timeout, and ``-protocol_whitelist file`` so a hostile file (e.g. a playlist
pointing at URLs) can't make the server fetch anything.
"""

from __future__ import annotations

import contextlib
import json
import os
import subprocess  # nosec B404
import wave
from dataclasses import dataclass, field
from typing import Any, Protocol


class ProcessingError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass
class ProcessResult:
    duration_seconds: float | None = None
    width: int | None = None
    height: int | None = None
    #: (variant name, local path, mime type)
    variants: list[tuple[str, str, str]] = field(default_factory=list)


class MediaProcessor(Protocol):
    def process(self, *, kind: str, mime_type: str, source: str, workdir: str) -> ProcessResult: ...

    def supports_clip(self, *, kind: str, mime_type: str) -> bool: ...

    def clip(
        self, *, kind: str, mime_type: str, source: str, start: float, end: float, workdir: str
    ) -> tuple[str, str]:
        """Cut ``[start, end)``; return (local path, mime type)."""


def _image_size(path: str) -> tuple[int | None, int | None]:
    try:
        from PIL import Image
    except ImportError:
        return None, None
    try:
        with Image.open(path) as image:
            return image.size
    except Exception as exc:
        raise ProcessingError("invalid_image") from exc


def _wav_duration(path: str) -> float:
    try:
        with contextlib.closing(wave.open(path, "rb")) as wav:
            return wav.getnframes() / float(wav.getframerate() or 1)
    except (wave.Error, EOFError) as exc:
        raise ProcessingError("invalid_audio") from exc


class BasicProcessor:
    """Dependency-free processing: enough for development and simple deployments."""

    def __init__(self, **_: Any) -> None:
        pass

    def process(self, *, kind: str, mime_type: str, source: str, workdir: str) -> ProcessResult:
        result = ProcessResult()
        if kind == "image":
            result.width, result.height = _image_size(source)
        elif mime_type == "audio/wav":
            result.duration_seconds = _wav_duration(source)
        return result

    def supports_clip(self, *, kind: str, mime_type: str) -> bool:
        return mime_type == "audio/wav"

    def clip(
        self, *, kind: str, mime_type: str, source: str, start: float, end: float, workdir: str
    ) -> tuple[str, str]:
        out = os.path.join(workdir, "clip.wav")
        try:
            with contextlib.closing(wave.open(source, "rb")) as src:
                rate = src.getframerate()
                src.setpos(min(int(start * rate), src.getnframes()))
                frames = src.readframes(max(int((end - start) * rate), 0))
                with contextlib.closing(wave.open(out, "wb")) as dst:
                    dst.setparams(src.getparams())
                    dst.writeframes(frames)
        except (wave.Error, EOFError) as exc:
            raise ProcessingError("invalid_audio") from exc
        return out, "audio/wav"


class FFmpegProcessor:
    def __init__(
        self, *, ffmpeg: str = "ffmpeg", ffprobe: str = "ffprobe", timeout: int = 1800, threads: int = 2
    ) -> None:
        self.ffmpeg = ffmpeg
        self.ffprobe = ffprobe
        self.timeout = timeout
        self.threads = threads

    def _run(self, args: list[str]) -> bytes:
        try:
            # Fixed argument list (never a shell) built from configured binaries and our own paths.
            completed = subprocess.run(  # noqa: S603  # nosec B603
                args, capture_output=True, timeout=self.timeout, check=False
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ProcessingError("processor_failed") from exc
        if completed.returncode != 0:
            raise ProcessingError("processor_failed")
        return completed.stdout

    def _ffmpeg(self, *args: str) -> None:
        self._run(
            [
                self.ffmpeg,
                "-nostdin",
                "-hide_banner",
                "-loglevel",
                "error",
                "-protocol_whitelist",
                "file",
                "-threads",
                str(self.threads),
                "-y",
                *args,
            ]
        )

    def probe(self, source: str) -> dict[str, Any]:
        out = self._run(
            [
                self.ffprobe,
                "-v",
                "error",
                "-protocol_whitelist",
                "file",
                "-print_format",
                "json",
                "-show_format",
                "-show_streams",
                source,
            ]
        )
        try:
            return json.loads(out or b"{}")
        except ValueError as exc:
            raise ProcessingError("probe_failed") from exc

    def process(self, *, kind: str, mime_type: str, source: str, workdir: str) -> ProcessResult:
        if kind == "image":
            result = ProcessResult()
            result.width, result.height = _image_size(source)
            return result
        if kind not in ("audio", "video"):
            return ProcessResult()
        info = self.probe(source)
        result = ProcessResult()
        with contextlib.suppress(TypeError, ValueError):
            result.duration_seconds = float((info.get("format") or {}).get("duration"))
        streams = info.get("streams") or []
        video = next((s for s in streams if s.get("codec_type") == "video"), None)
        has_audio = any(s.get("codec_type") == "audio" for s in streams)
        if video:
            result.width, result.height = video.get("width"), video.get("height")
        if has_audio:
            mp3 = os.path.join(workdir, "audio.mp3")
            self._ffmpeg("-i", source, "-vn", "-codec:a", "libmp3lame", "-b:a", "128k", mp3)
            result.variants.append(("mp3", mp3, "audio/mpeg"))
        if kind == "video" and video:
            mp4 = os.path.join(workdir, "video_720p.mp4")
            self._ffmpeg(
                "-i",
                source,
                "-vf",
                "scale=-2:'min(720,ih)'",
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "23",
                "-c:a",
                "aac",
                "-b:a",
                "128k",
                "-movflags",
                "+faststart",
                mp4,
            )
            result.variants.append(("mp4_720p", mp4, "video/mp4"))
            poster = os.path.join(workdir, "poster.jpg")
            self._ffmpeg("-ss", "1", "-i", source, "-frames:v", "1", "-vf", "scale=-2:720", poster)
            result.variants.append(("poster", poster, "image/jpeg"))
        return result

    def supports_clip(self, *, kind: str, mime_type: str) -> bool:
        return kind in ("audio", "video")

    def clip(
        self, *, kind: str, mime_type: str, source: str, start: float, end: float, workdir: str
    ) -> tuple[str, str]:
        if kind == "video":
            out = os.path.join(workdir, "clip.mp4")
            self._ffmpeg(
                "-ss",
                f"{start:.3f}",
                "-to",
                f"{end:.3f}",
                "-i",
                source,
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-c:a",
                "aac",
                "-movflags",
                "+faststart",
                out,
            )
            return out, "video/mp4"
        out = os.path.join(workdir, "clip.mp3")
        self._ffmpeg(
            "-ss",
            f"{start:.3f}",
            "-to",
            f"{end:.3f}",
            "-i",
            source,
            "-vn",
            "-codec:a",
            "libmp3lame",
            "-b:a",
            "128k",
            out,
        )
        return out, "audio/mpeg"


def get_processor() -> MediaProcessor:
    from django.utils.module_loading import import_string

    from university.media.conf import media_settings

    cls = import_string(media_settings.get("PROCESSOR"))
    return cls(**(media_settings.get("PROCESSOR_OPTIONS") or {}))
