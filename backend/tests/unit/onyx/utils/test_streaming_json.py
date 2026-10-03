"""Streamed JSON objects report the same text as a complete parse."""

import json
import random

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

    @pytest.mark.parametrize("text", ["[1, 2]", '"text"', "null", "true", "42"])
    def test_non_object_documents_parse_as_empty(self, text: str) -> None:
        assert parse_partial_object(text) == {}

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

    def test_object_streamed_in_two_halves(self) -> None:
        joined, final = _stream(['{"code": "x = ', '1"}'])

        assert joined == {"code": "x = 1"}
        assert final == {"code": "x = 1"}

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

    @pytest.mark.parametrize(
        "escaped, expected",
        [
            ("a\\nb", "a\nb"),
            ("a\\tb", "a\tb"),
            ('say \\"hi\\"', 'say "hi"'),
            ("back\\\\slash", "back\\slash"),
            ("caf\\u00e9", "café"),
            ("\\ud83d\\ude00", "😀"),
        ],
    )
    def test_escapes_split_at_every_position_decode_like_a_complete_parse(
        self, escaped: str, expected: str
    ) -> None:
        document = '{"text": "' + escaped + '"}'
        for cut in range(1, len(document)):
            joined, final = _stream([document[:cut], document[cut:]])

            assert joined == {"text": expected}
            assert final == {"text": expected}

    def test_split_surrogate_pair_never_reports_a_lone_surrogate(self) -> None:
        document = '{"text": "hi \\ud83d\\ude00 there"}'
        for cut in range(1, len(document)):
            previous: dict[str, JsonValue] = {}
            for text in (document[:cut], document):
                current = parse_partial_object(text)
                for added in appended_text(previous, current).values():
                    added.encode("utf-8")
                previous = current

    def test_non_string_fields_report_no_text(self) -> None:
        joined, final = _stream(['{"n": 12', '3, "flag": tr', 'ue, "items": ["a"]}'])

        assert joined == {}
        assert final == {"n": 123, "flag": True, "items": ["a"]}

    def test_repeated_key_that_replaces_text_reports_only_later_appends(
        self,
    ) -> None:
        joined, final = _stream(['{"a": "xyz"', ', "a": "q', 'r"}'])

        assert joined == {"a": "xyzr"}
        assert final == {"a": "qr"}


class TestToolCallArguments:
    @pytest.mark.parametrize("chunk_size", [1, 3, 7, 50])
    def test_code_with_newlines_quotes_and_escapes(self, chunk_size: int) -> None:
        arguments: dict[str, JsonValue] = {
            "code": 'def f(x):\n    return "a\\tb" + x  # é 😀\n',
            "timeout": 30,
            "lang": "python",
        }
        document = json.dumps(arguments)
        chunks = [
            document[start : start + chunk_size]
            for start in range(0, len(document), chunk_size)
        ]

        joined, final = _stream(chunks)

        assert joined == {"code": arguments["code"], "lang": "python"}
        assert final == arguments

    def test_random_documents_match_a_complete_parse(self) -> None:
        rng = random.Random(15188)
        alphabet = ["a", " ", "é", "😀", "\n", '"', "\\", "/", "\x00"]
        for _ in range(300):
            value: dict[str, JsonValue] = {
                f"k{index}": "".join(
                    rng.choice(alphabet) for _ in range(rng.randint(0, 12))
                )
                for index in range(rng.randint(1, 3))
            }
            document = json.dumps(value, ensure_ascii=rng.random() < 0.5)
            cuts = sorted(
                rng.sample(range(1, len(document)), min(4, len(document) - 1))
            )
            chunks = [
                document[start:end]
                for start, end in zip([0, *cuts], [*cuts, None], strict=True)
            ]

            joined, final = _stream(chunks)

            assert final == value
            assert joined == {key: text for key, text in value.items() if text}
