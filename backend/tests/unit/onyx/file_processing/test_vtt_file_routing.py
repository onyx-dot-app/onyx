"""A WebVTT transcript arriving as a file has to reach the parser Onyx ships.

`parse_vtt_transcript` is reachable only from the Teams and Zoom connectors, so
a `.vtt` that arrives as a file (SharePoint, Google Drive, the local file
connector, a direct upload) was dropped before download and, where it did reach
extraction, read verbatim with its timing lines and cue numbers intact.

Reported in #15114. No new parser, only routing.
"""

from io import BytesIO
from unittest.mock import patch

from onyx.file_processing.extract_file_text import (
    extract_file_text_locally,
    extract_text_and_images,
)
from onyx.file_processing.file_types import OnyxFileExtensions

# The shape Microsoft Graph exports for a Teams meeting: speaker in a voice span.
_VTT = b"""WEBVTT

1
00:00:13.900 --> 00:00:17.200
<v Jane Doe>the quarterly numbers came in this morning</v>

2
00:00:17.200 --> 00:00:19.800
<v Sam Patel>and they are better than we modelled</v>
"""


def _text(raw: bytes = _VTT) -> str:
    return extract_file_text_locally(BytesIO(raw), "meeting.vtt")


def test_vtt_is_an_allowed_extension() -> None:
    # Connectors gate on this set before downloading, so a .vtt outside it is
    # never fetched and no document is created.
    assert ".vtt" in OnyxFileExtensions.ALL_ALLOWED_EXTENSIONS


def test_local_extraction_strips_the_cue_scaffolding() -> None:
    text = _text()

    assert "00:00:13.900" not in text
    assert "WEBVTT" not in text
    assert "<v" not in text


def test_local_extraction_keeps_the_spoken_words() -> None:
    text = _text()

    assert "the quarterly numbers came in this morning" in text
    assert "they are better than we modelled" in text


def test_local_extraction_keeps_the_speaker() -> None:
    # Matches what the Teams connector already does with the same transcript.
    assert "Jane Doe" in _text()


def test_extract_text_and_images_routes_vtt_too() -> None:
    # The other extraction path. Without it the file is fetched and then read
    # verbatim, which is the second half of the report. The Unstructured key
    # lives in Redis, so it is stubbed out to keep this a unit test.
    with patch(
        "onyx.file_processing.extract_file_text.get_unstructured_api_key",
        return_value=None,
    ):
        result = extract_text_and_images(BytesIO(_VTT), "meeting.vtt")

    assert "00:00:13.900" not in result.text_content
    assert "the quarterly numbers came in this morning" in result.text_content


def test_a_plain_text_file_is_unaffected() -> None:
    text = extract_file_text_locally(BytesIO(b"just some notes\n"), "notes.txt")

    assert text.strip() == "just some notes"
