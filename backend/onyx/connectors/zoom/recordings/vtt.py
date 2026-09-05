import re

# Anchored and shaped like a real timestamp, so a speaker saying something
# like "the flow goes A --> B" isn't mistaken for a timing line and dropped.
_TIMING_LINE_RE = re.compile(r"^(?:\d+:)?\d{1,2}:\d{2}[.,]\d{1,3}\s*-->")

_NON_CUE_BLOCK_RE = re.compile(r"^(WEBVTT|NOTE|STYLE|REGION)\b", re.IGNORECASE)

_CUE_TAG_RE = re.compile(r"<[^>]*>")


def parse_vtt_transcript(vtt_content: str) -> str:
    """Follows the W3C WebVTT spec, because Zoom names the file type but never
    defines the layout inside it. Real Zoom files put the speaker inline in
    the cue text ("Jane Doe: hello"), which is undocumented and could change.
    """
    normalized = vtt_content.lstrip("﻿").replace("\r\n", "\n").replace("\r", "\n")

    paragraphs: list[str] = []
    for block in normalized.split("\n\n"):
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if not lines or _NON_CUE_BLOCK_RE.match(lines[0]):
            continue

        # Take the speech by position rather than by what it looks like, so a
        # cue that is only a number survives instead of reading as a cue index.
        timing_index = next(
            (i for i, line in enumerate(lines) if _TIMING_LINE_RE.match(line)), None
        )
        if timing_index is None:
            continue

        spoken = [
            stripped
            for line in lines[timing_index + 1 :]
            if (stripped := _CUE_TAG_RE.sub("", line).strip())
        ]
        if spoken:
            paragraphs.append(" ".join(spoken))

    return "\n\n".join(paragraphs)
