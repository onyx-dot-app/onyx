"""Streamed JSON objects report the same text as a complete parse."""

import pytest
from pydantic import JsonValue

from onyx.utils.streaming_json import appended_text, parse_partial_object


def _stream(chunks: list[str]) -> tuple[dict[str, str], dict[str, JsonValue]]:
    """Feed chunks the way callers do and join the text added to each field."""
    text = ""
    previous: dict[str, JsonValue] = {}
    joined: dict[str, str] = {}
    for chunk in chunks:
        text += chunk
        current = parse_partial_object(text)
        for key, added in appended_text(previous, current).items():
            joined[key] = joined.get(key, "") + added
        previous = current
    return joined, previous


class TestParsePartialObject:
    def test_complete_object(self) -> None:
        assert parse_partial_object(
            '{"s": "x", "n": -1.5, "t": true, "f": false, "z": null}'
        ) == {"s": "x", "n": -1.5, "t": True, "f": False, "z": None}

    def test_empty_object(self) -> None:
        assert parse_partial_object("{}") == {}

    def test_nested_values(self) -> None:
        assert parse_partial_object('{"o": {"a": 1}, "l": ["x", "y"]}') == {
            "o": {"a": 1},
            "l": ["x", "y"],
        }

    @pytest.mark.parametrize("text", ["", "   ", "\n"])
    def test_blank_text_parses_as_empty(self, text: str) -> None:
        assert parse_partial_object(text) == {}

    def test_incomplete_string_keeps_complete_characters(self) -> None:
        assert parse_partial_object('{"code": "prin') == {"code": "prin"}

    def test_incomplete_nested_values_are_kept(self) -> None:
        assert parse_partial_object('{"l": ["x", "y') == {"l": ["x", "y"]}

    @pytest.mark.parametrize("text", ['{"flag": tru', '{"n": 12.', '{"z": nu'])
    def test_incomplete_literals_and_numbers_are_left_out(self, text: str) -> None:
        assert parse_partial_object(text) == {}

    @pytest.mark.parametrize(
        "text",
        [
            "{a",
            '{"a" 1',
            '{"a": "\\q"}',
            '{"a": "\\uZZZZ"}',
            '{"a": "\\ud83d\\ude٠٠"}',
            '{"a": "raw\nnewline"}',
            '{"a": "\\ud83d"}',
            '{"a": "\\ude00"}',
        ],
    )
    def test_invalid_json_raises_value_error(self, text: str) -> None:
        with pytest.raises(ValueError):
            parse_partial_object(text)

    def test_text_with_a_lone_surrogate_raises_value_error(self) -> None:
        with pytest.raises(ValueError):
            parse_partial_object('{"a": "' + chr(0xD83D) + '"}')


class TestAppendedText:
    def test_new_string_field_reports_all_its_text(self) -> None:
        assert appended_text({}, {"a": "xy"}) == {"a": "xy"}

    def test_grown_string_reports_only_new_text(self) -> None:
        assert appended_text({"a": "xy"}, {"a": "xyz"}) == {"a": "z"}

    def test_unchanged_and_empty_strings_report_nothing(self) -> None:
        assert appended_text({"a": "xy"}, {"a": "xy", "b": ""}) == {}

    def test_non_string_values_report_nothing(self) -> None:
        current: dict[str, JsonValue] = {
            "n": 1,
            "t": True,
            "z": None,
            "o": {"s": "x"},
            "l": ["x"],
        }
        assert appended_text({}, current) == {}

    def test_value_that_becomes_a_string_reports_all_its_text(self) -> None:
        assert appended_text({"a": 1}, {"a": "x"}) == {"a": "x"}

    def test_replaced_string_reports_nothing(self) -> None:
        assert appended_text({"a": "xyz"}, {"a": "q"}) == {}


class TestStreaming:
    def test_string_value_streamed_one_character_at_a_time(self) -> None:
        document = '{"code": "print(1)"}'
        text = ""
        previous: dict[str, JsonValue] = {}
        added: list[str] = []
        for char in document:
            text += char
            current = parse_partial_object(text)
            added.append(appended_text(previous, current).get("code", ""))
            previous = current

        assert "".join(added) == "print(1)"
        assert all(len(piece) <= 1 for piece in added)

    def test_multiple_fields_report_only_their_new_text(self) -> None:
        text = ""
        results = []
        previous: dict[str, JsonValue] = {}
        for chunk in ['{"code": "ab', 'c", "lang": "py', 'thon"}']:
            text += chunk
            current = parse_partial_object(text)
            results.append(appended_text(previous, current))
            previous = current

        assert results == [
            {"code": "ab"},
            {"code": "c", "lang": "py"},
            {"lang": "thon"},
        ]

    def test_repeated_key_that_replaces_text_reports_only_later_appends(
        self,
    ) -> None:
        joined, final = _stream(['{"a": "xyz"', ', "a": "q', 'r"}'])

        assert joined == {"a": "xyzr"}
        assert final == {"a": "qr"}
