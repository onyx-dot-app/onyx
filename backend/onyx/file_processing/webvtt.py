"""Turns a WebVTT transcript into indexable text.

Zoom and Microsoft Teams both export meeting transcripts as WebVTT and neither
documents the layout inside the file, so this follows the W3C spec. Cue text is
found by position, never by shape: a speaker can say "A --> B" and a cue can be
nothing but a number, so matching either as markup deletes real speech.
"""

import re
from html import unescape

_TIMING_LINE_RE = re.compile(r"^(?:\d+:)?\d{1,2}:\d{2}[.,]\d{1,3}\s*-->")

# Matching loosely here eats a cue whose identifier merely starts with one of
# these words, taking the speech under it. Only NOTE and WEBVTT may carry
# trailing text.
_NON_CUE_BLOCK_RE = re.compile(r"^(?:(?:WEBVTT|NOTE)(?:[ \t].*)?|STYLE|REGION)$")

_CUE_TAG_RE = re.compile(r"<[^>]*>")

# A voice span names its speaker in the tag's annotation: <v Jane Doe> or, with
# classes, <v.loud.fast Jane Doe>. Teams writes one per cue, Zoom writes none
# and puts "Jane Doe: " in the text instead. The spec separates classes from
# the annotation with a space or tab only, so a non-breaking space is not one.
_VOICE_TAG_RE = re.compile(r"<v(?:\.[^ \t>]*)?[ \t]+([^>]+)>")

# A span starts at its tag and ends at </v>. Speech after the close and before
# the next tag belongs to nobody, so both are boundaries.
_VOICE_BOUNDARY_RE = re.compile(rf"{_VOICE_TAG_RE.pattern}|</v>")


def _clean_cue_line(line: str) -> str:
    """WebVTT forbids a literal "&", so "R&D" arrives as "R&amp;D". Strip markup
    before decoding, or an escaped "&lt;v Jane&gt;" becomes a tag and gets
    deleted. The decoded non-breaking space goes too, since it will not match a
    typed space in search.
    """
    decoded = unescape(_CUE_TAG_RE.sub("", line))
    return decoded.replace("\xa0", " ").strip()


def _speaker_paragraphs(cue_lines: list[str]) -> list[str]:
    """One paragraph per stretch of speech, "Jane Doe: hello" inside a voice
    span, unnamed outside one, so a cue in which two people speak keeps both
    names and a note between them is attributed to neither."""
    text = " ".join(cue_lines)
    paragraphs: list[str] = []
    speaker: str | None = None
    start = 0
    for boundary in _VOICE_BOUNDARY_RE.finditer(text):
        if spoken := _clean_cue_line(text[start : boundary.start()]):
            paragraphs.append(f"{speaker}: {spoken}" if speaker else spoken)
        start = boundary.end()
        name = boundary.group(1)
        speaker = unescape(name).replace("\xa0", " ").strip() or None if name else None
    if spoken := _clean_cue_line(text[start:]):
        paragraphs.append(f"{speaker}: {spoken}" if speaker else spoken)
    return paragraphs


def parse_vtt_transcript(vtt_content: str, keep_speakers: bool = False) -> str:
    """One paragraph per cue. With ``keep_speakers`` a cue spoken inside a
    voice span reads "Jane Doe: hello", the shape Zoom's own transcripts have."""
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

        cue_lines = lines[timing_index + 1 :]
        if keep_speakers:
            paragraphs.extend(_speaker_paragraphs(cue_lines))
            continue
        spoken = [cleaned for line in cue_lines if (cleaned := _clean_cue_line(line))]
        if spoken:
            paragraphs.append(" ".join(spoken))

    return "\n\n".join(paragraphs)
