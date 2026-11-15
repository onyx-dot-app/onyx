import pytest

from onyx.file_processing.webvtt import parse_vtt_transcript

# A real Zoom audio_transcript.vtt shape, not an invented one.
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

# The shape Microsoft Graph exports for a Teams meeting: the speaker lives in
# a voice span, not in the text.
_TEAMS_VTT = """WEBVTT

00:00:03.120 --> 00:00:06.480
<v Sarah Chen>So the thing I keep coming back to is</v>

00:00:06.480 --> 00:00:09.760
<v Sarah Chen>that I can't tell if I'm building the right thing.</v>

00:00:09.760 --> 00:00:11.200
<v Marcus Webb>Yeah.</v>
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
    """Whatever this returns gets indexed, so parser scaffolding leaking
    through would show up in search results."""

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


class TestParseVttDecodesCharacterReferences:
    """Drop the decoding and "R&D" gets indexed as "R&amp;D", so nobody
    searching for it finds the meeting."""

    def test_ampersand_is_decoded(self) -> None:
        vtt = "WEBVTT\n\n1\n00:00:01.000 --> 00:00:02.000\nJane: our R&amp;D team\n"
        assert parse_vtt_transcript(vtt) == "Jane: our R&D team"

    def test_angle_brackets_are_decoded(self) -> None:
        vtt = "WEBVTT\n\n1\n00:00:01.000 --> 00:00:02.000\nJane: a &lt;div&gt; tag\n"
        assert parse_vtt_transcript(vtt) == "Jane: a <div> tag"

    def test_numeric_reference_is_decoded(self) -> None:
        vtt = "WEBVTT\n\n1\n00:00:01.000 --> 00:00:02.000\nJane: it&#39;s fine\n"
        assert parse_vtt_transcript(vtt) == "Jane: it's fine"

    def test_non_breaking_space_becomes_a_normal_space(self) -> None:
        vtt = "WEBVTT\n\n1\n00:00:01.000 --> 00:00:02.000\nJane: a&nbsp;b\n"
        assert parse_vtt_transcript(vtt) == "Jane: a b"
        assert "\xa0" not in parse_vtt_transcript(vtt)

    def test_escaped_markup_survives_as_text(self) -> None:
        vtt = (
            "WEBVTT\n\n1\n00:00:01.000 --> 00:00:02.000\n"
            "&lt;v Jane&gt;hello&lt;/v&gt;\n"
        )
        # Guards the order: decoding first would read this as a tag.
        assert parse_vtt_transcript(vtt) == "<v Jane>hello</v>"


class TestParseVttKeepsCuesNamedLikeReservedWords:
    """A cue identifier is free text, so matching these words too loosely throws
    away the block and the speech under it."""

    @pytest.mark.parametrize(
        "identifier", ["1", "NOTE-1", "REGION:2", "STYLE 3", "note-x", "NOTES"]
    )
    def test_identifier_starting_with_a_reserved_word_is_still_a_cue(
        self, identifier: str
    ) -> None:
        vtt = (
            f"WEBVTT\n\n{identifier}\n"
            "00:00:01.000 --> 00:00:02.000\nJane: real speech\n"
        )
        assert parse_vtt_transcript(vtt) == "Jane: real speech"

    @pytest.mark.parametrize(
        "block", ["NOTE a comment", "NOTE", "STYLE", "REGION", "WEBVTT - title"]
    )
    def test_genuine_non_cue_blocks_are_still_dropped(self, block: str) -> None:
        vtt = (
            f"WEBVTT\n\n{block}\npayload\n\n"
            "1\n00:00:01.000 --> 00:00:02.000\nJane: kept\n"
        )
        assert parse_vtt_transcript(vtt) == "Jane: kept"


class TestParseVttKeepsSpeakers:
    """Teams names the speaker in a voice span, so dropping the markup drops
    who said it. The mode is opt-in so Zoom's output stays as it was."""

    def test_voice_spans_become_speaker_prefixes(self) -> None:
        assert parse_vtt_transcript(_TEAMS_VTT, keep_speakers=True) == (
            "Sarah Chen: So the thing I keep coming back to is\n\n"
            "Sarah Chen: that I can't tell if I'm building the right thing.\n\n"
            "Marcus Webb: Yeah."
        )

    def test_zoom_output_is_unchanged_with_speakers_on(self) -> None:
        assert parse_vtt_transcript(_ZOOM_VTT, keep_speakers=True) == (
            parse_vtt_transcript(_ZOOM_VTT)
        )

    def test_speaker_is_off_by_default(self) -> None:
        assert parse_vtt_transcript(_TEAMS_VTT).startswith("So the thing")

    def test_voice_span_classes_are_not_part_of_the_name(self) -> None:
        vtt = (
            "WEBVTT\n\n00:00:01.000 --> 00:00:02.000\n"
            "<v.loud.fast Jane Doe>hello <i>there</i></v>\n"
        )
        assert parse_vtt_transcript(vtt, keep_speakers=True) == "Jane Doe: hello there"

    def test_multiline_cue_names_its_speaker_once(self) -> None:
        vtt = (
            "WEBVTT\n\n00:00:01.000 --> 00:00:02.000\n"
            "<v Jane Doe>This sentence wraps\n"
            "across two lines.</v>\n"
        )
        assert (
            parse_vtt_transcript(vtt, keep_speakers=True)
            == "Jane Doe: This sentence wraps across two lines."
        )

    def test_speaker_name_is_decoded_like_speech(self) -> None:
        vtt = (
            "WEBVTT\n\n00:00:01.000 --> 00:00:02.000\n"
            "<v Jane&nbsp;O&#39;Brien>hello</v>\n"
        )
        assert parse_vtt_transcript(vtt, keep_speakers=True) == "Jane O'Brien: hello"

    def test_a_non_breaking_space_in_a_class_is_not_the_separator(self) -> None:
        vtt = (
            "WEBVTT\n\n00:00:01.000 --> 00:00:02.000\n<v.loud\xa0fast Jane>hello</v>\n"
        )
        assert parse_vtt_transcript(vtt, keep_speakers=True) == "Jane: hello"

    def test_two_speakers_in_one_cue_keep_both_names(self) -> None:
        vtt = (
            "WEBVTT\n\n00:00:01.000 --> 00:00:02.000\n"
            "<v Jane>Hello</v> <v John>Hi</v>\n"
        )
        assert (
            parse_vtt_transcript(vtt, keep_speakers=True) == "Jane: Hello\n\nJohn: Hi"
        )

    def test_speech_before_the_first_span_has_no_name(self) -> None:
        vtt = "WEBVTT\n\n00:00:01.000 --> 00:00:02.000\n[laughter] <v Jane>hello</v>\n"
        assert (
            parse_vtt_transcript(vtt, keep_speakers=True) == "[laughter]\n\nJane: hello"
        )

    def test_speech_between_spans_belongs_to_nobody(self) -> None:
        vtt = (
            "WEBVTT\n\n00:00:01.000 --> 00:00:02.000\n"
            "<v Jane>Hello</v> [laughter] <v John>Hi</v> [applause]\n"
        )
        assert parse_vtt_transcript(vtt, keep_speakers=True) == (
            "Jane: Hello\n\n[laughter]\n\nJohn: Hi\n\n[applause]"
        )

    def test_an_unclosed_span_names_its_speaker(self) -> None:
        vtt = "WEBVTT\n\n00:00:01.000 --> 00:00:02.000\n<v Jane>hello\n"
        assert parse_vtt_transcript(vtt, keep_speakers=True) == "Jane: hello"

    def test_a_cue_without_a_voice_span_has_no_prefix(self) -> None:
        vtt = "WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nhello there\n"
        assert parse_vtt_transcript(vtt, keep_speakers=True) == "hello there"

    def test_escaped_voice_span_is_speech_not_a_speaker(self) -> None:
        vtt = "WEBVTT\n\n00:00:01.000 --> 00:00:02.000\n&lt;v Jane&gt;hello&lt;/v&gt;\n"
        assert parse_vtt_transcript(vtt, keep_speakers=True) == "<v Jane>hello</v>"
