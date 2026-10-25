"""Transcript parsing and rendering (WebVTT, SubRip, plain text).

Input is untrusted: size-limited, markup stripped from cue text, timestamps
validated. Output is a list of cues ``{"start", "end", "text"}`` plus plain
text for search and accessibility.
"""

from __future__ import annotations

import html
import re
from typing import Any

from university.core.exceptions import ValidationError

TIMESTAMP = re.compile(r"(?:(\d{1,2}):)?(\d{1,2}):(\d{2})[.,](\d{3})")
ARROW = re.compile(rf"({TIMESTAMP.pattern})\s*-->\s*({TIMESTAMP.pattern})")
TAG = re.compile(r"<[^>]{0,200}>")
MAX_CUES = 20000


def _seconds(match: tuple[str | None, ...]) -> float:
    hours, minutes, seconds, millis = match
    return int(hours or 0) * 3600 + int(minutes) * 60 + int(seconds) + int(millis) / 1000


def _clean(text: str) -> str:
    return html.unescape(TAG.sub("", text)).strip()


def parse(content: str, source_format: str) -> tuple[list[dict[str, Any]], str]:
    if source_format == "text":
        text = _clean(content)
        return [], text
    cues: list[dict[str, Any]] = []
    blocks = re.split(r"\r?\n\s*\r?\n", content.replace("﻿", "").strip())
    for block in blocks:
        lines = [line for line in block.splitlines() if line.strip()]
        timing_index = next((i for i, line in enumerate(lines) if "-->" in line), None)
        if timing_index is None:
            continue  # WEBVTT header, NOTE, STYLE or SRT counters without timing.
        found = TIMESTAMP.findall(lines[timing_index])
        if len(found) < 2:
            raise ValidationError(details={"content": [f"Bad timing line: {lines[timing_index][:60]}"]})
        start, end = _seconds(found[0]), _seconds(found[1])
        if end < start:
            raise ValidationError(details={"content": ["A cue ends before it starts."]})
        text = _clean(" ".join(lines[timing_index + 1 :]))
        if text:
            cues.append({"start": round(start, 3), "end": round(end, 3), "text": text[:2000]})
        if len(cues) > MAX_CUES:
            raise ValidationError(details={"content": ["Too many cues."]})
    if not cues:
        raise ValidationError(details={"content": ["No cues found."]})
    return cues, "\n".join(cue["text"] for cue in cues)


def _stamp(seconds: float) -> str:
    millis = round(seconds * 1000)
    hours, rest = divmod(millis, 3_600_000)
    minutes, rest = divmod(rest, 60_000)
    secs, millis = divmod(rest, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}.{millis:03d}"


def to_vtt(cues: list[dict[str, Any]], text: str = "") -> str:
    lines = ["WEBVTT", ""]
    if not cues and text:
        return "WEBVTT\n\nNOTE This transcript has no timings.\n\n" + text.replace("-->", "->") + "\n"
    for i, cue in enumerate(cues, 1):
        lines += [str(i), f"{_stamp(cue['start'])} --> {_stamp(cue['end'])}", cue["text"].replace("-->", "->"), ""]
    return "\n".join(lines)
