from onyx.connectors.zoom.recordings.vtt import parse_vtt_transcript

# Shaped after a real Zoom audio_transcript.vtt: numbered cue, timing line,
# then the speaker name inline with the speech.
_ZOOM_VTT = """WEBVTT

1
00:00:03.120 --> 00:00:06.480
Sarah Chen: So the thing I keep coming back to is

2
00:00:06.480 --> 00:00:09.760
Sarah Chen: that I can't tell if I'm building the right thing.

3
00:00:09.760 --> 00:00:11.200
Marcus Webb: Yeah.
"""


class TestParseVttTranscript:
    def test_keeps_speech_and_drops_cue_scaffolding(self) -> None:
        text = parse_vtt_transcript(_ZOOM_VTT)

        assert text == (
            "Sarah Chen: So the thing I keep coming back to is\n\n"
            "Sarah Chen: that I can't tell if I'm building the right thing.\n\n"
            "Marcus Webb: Yeah."
        )

    def test_empty_vtt_yields_empty_string(self) -> None:
        assert parse_vtt_transcript("WEBVTT\n") == ""

    def test_multiline_cue_is_joined(self) -> None:
        vtt = (
            "WEBVTT\n\n"
            "1\n"
            "00:00:00.000 --> 00:00:02.000\n"
            "Jane Doe: This sentence wraps\n"
            "across two lines.\n"
        )
        assert (
            parse_vtt_transcript(vtt)
            == "Jane Doe: This sentence wraps across two lines."
        )

    def test_crlf_line_endings(self) -> None:
        vtt = "WEBVTT\r\n\r\n1\r\n00:00:01.000 --> 00:00:02.000\r\nJane: hello\r\n"
        assert parse_vtt_transcript(vtt) == "Jane: hello"

    def test_cue_settings_on_timing_line_are_dropped(self) -> None:
        vtt = (
            "WEBVTT\n\n1\n"
            "00:00:01.000 --> 00:00:02.000 align:start position:0%\n"
            "Jane: hello\n"
        )
        assert parse_vtt_transcript(vtt) == "Jane: hello"


class TestParseVttKeepsSpeechThatLooksLikeScaffolding:
    """These cues would be dropped by shape-matching on "is it a number" or
    "does it contain an arrow", which silently loses what someone said."""

    def test_speech_containing_an_arrow_is_kept(self) -> None:
        vtt = (
            "WEBVTT\n\n1\n00:00:01.000 --> 00:00:02.000\n"
            "Jane: the flow goes A --> B here\n"
        )
        assert parse_vtt_transcript(vtt) == "Jane: the flow goes A --> B here"

    def test_cue_that_is_only_a_number_is_kept(self) -> None:
        vtt = "WEBVTT\n\n1\n00:00:01.000 --> 00:00:02.000\n42\n"
        assert parse_vtt_transcript(vtt) == "42"


class TestParseVttDropsNonSpeechBlocks:
    """Anything that reaches the return value gets indexed and shows up in
    search, so non-speech blocks have to be excluded."""

    def test_header_with_trailing_text_is_dropped(self) -> None:
        vtt = (
            "WEBVTT - This file has a title\n\n"
            "1\n00:00:01.000 --> 00:00:02.000\nJane: hello\n"
        )
        assert parse_vtt_transcript(vtt) == "Jane: hello"

    def test_byte_order_mark_is_dropped(self) -> None:
        vtt = "﻿WEBVTT\n\n1\n00:00:01.000 --> 00:00:02.000\nJane: hello\n"
        assert parse_vtt_transcript(vtt) == "Jane: hello"

    def test_note_block_is_dropped(self) -> None:
        vtt = (
            "WEBVTT\n\nNOTE This transcript was auto-generated\n\n"
            "1\n00:00:01.000 --> 00:00:02.000\nJane: hello\n"
        )
        assert parse_vtt_transcript(vtt) == "Jane: hello"

    def test_style_block_is_dropped(self) -> None:
        vtt = (
            "WEBVTT\n\nSTYLE\n::cue { color: yellow }\n\n"
            "1\n00:00:01.000 --> 00:00:02.000\nJane: hello\n"
        )
        assert parse_vtt_transcript(vtt) == "Jane: hello"

    def test_cue_markup_is_stripped_but_speech_survives(self) -> None:
        vtt = (
            "WEBVTT\n\n1\n00:00:01.000 --> 00:00:02.000\n"
            "<v Jane Doe>hello <i>there</i></v>\n"
        )
        assert parse_vtt_transcript(vtt) == "hello there"
