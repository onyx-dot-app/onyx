"""Turns a Zoom transcript's WebVTT into indexable text.

Zoom names the file type but never defines the layout inside, so this follows
the W3C spec; real files put the speaker inline ("Jane Doe: hello"), which is
undocumented. Cue text is found by position, never by shape — a speaker can
say "A --> B" and a cue can be nothing but a number, and matching either as
markup deletes real speech.
"""

import html
import re

_TIMING_LINE_RE = re.compile(r"^(?:\d+:)?\d{1,2}:\d{2}[.,]\d{1,3}\s*-->")

_NON_CUE_BLOCK_RE = re.compile(r"^(WEBVTT|NOTE|STYLE|REGION)\b", re.IGNORECASE)

_CUE_TAG_RE = re.compile(r"<[^>]*>")


def _clean_cue_line(line: str) -> str:
    """WebVTT forbids a literal "&", so someone saying "R&D" arrives as
    "R&amp;D". Decode only after stripping markup, or an escaped
    "&lt;v Jane&gt;" turns into a tag and gets deleted. The decoded
    non-breaking space goes too, since it will not match a typed space.
    """
    decoded = html.unescape(_CUE_TAG_RE.sub("", line))
    return decoded.replace("\xa0", " ").strip()


def parse_vtt_transcript(vtt_content: str) -> str:
    normalized = vtt_content.lstrip("﻿").replace("\r\n", "\n").replace("\r", "\n")

    paragraphs: list[str] = []
    for block in normalized.split("\n\n"):
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if not lines or _NON_CUE_BLOCK_RE.match(lines[0]):
            continue

        timing_index = next(
            (i for i, line in enumerate(lines) if _TIMING_LINE_RE.match(line)), None
        )
        if timing_index is None:
            continue

        spoken = [
            cleaned
            for line in lines[timing_index + 1 :]
            if (cleaned := _clean_cue_line(line))
        ]
        if spoken:
            paragraphs.append(" ".join(spoken))

    return "\n\n".join(paragraphs)
