"""Streamed JSON objects report the same text as a complete parse."""

import json
import random

import pytest

from onyx.utils.streaming_json import StreamingJsonParser


def _stream(chunks: list[str]) -> tuple[dict[str, str], StreamingJsonParser]:
    parser = StreamingJsonParser()
    joined: dict[str, str] = {}
    for chunk in chunks:
        for key, text in parser.feed(chunk).items():
            joined[key] = joined.get(key, "") + text
    return joined, parser


def test_string_value_streamed_one_character_at_a_time() -> None:
    document = '{"code": "print(1)"}'
    parser = StreamingJsonParser()
    texts = [parser.feed(char).get("code", "") for char in document]

    assert "".join(texts) == "print(1)"
    assert all(len(text) <= 1 for text in texts)


def test_deltas_contain_only_new_text_for_each_field() -> None:
    parser = StreamingJsonParser()

    assert parser.feed('{"code": "ab') == {"code": "ab"}
    assert parser.feed('c", "lang": "py') == {"code": "c", "lang": "py"}
    assert parser.feed('thon"}') == {"lang": "thon"}
    assert parser.snapshot() == {"code": "abc", "lang": "python"}


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
    escaped: str, expected: str
) -> None:
    document = '{"text": "' + escaped + '"}'
    for cut in range(1, len(document)):
        joined, parser = _stream([document[:cut], document[cut:]])

        assert joined == {"text": expected}
        assert parser.snapshot() == {"text": expected}


def test_split_surrogate_pair_never_reports_a_lone_surrogate() -> None:
    document = '{"text": "hi \\ud83d\\ude00 there"}'
    for cut in range(1, len(document)):
        parser = StreamingJsonParser()
        for fragment in (document[:cut], document[cut:]):
            for text in parser.feed(fragment).values():
                text.encode("utf-8")

        assert parser.snapshot() == {"text": "hi 😀 there"}


def test_non_string_values_appear_only_in_the_snapshot() -> None:
    joined, parser = _stream(['{"n": 12', '3, "flag": tr', 'ue, "items": ["a"]}'])

    assert joined == {}
    assert parser.snapshot() == {"n": 123, "flag": True, "items": ["a"]}


def test_incomplete_literal_is_left_out_of_the_snapshot() -> None:
    parser = StreamingJsonParser()
    parser.feed('{"code": "x", "flag": tru')

    assert parser.snapshot() == {"code": "x"}


def test_repeated_key_that_replaces_text_reports_no_delta() -> None:
    parser = StreamingJsonParser()

    assert parser.feed('{"a": "xyz"') == {"a": "xyz"}
    assert parser.feed(', "a": "q') == {}
    assert parser.feed('r"}') == {"a": "r"}


@pytest.mark.parametrize("fragment", ["", "   ", "\n"])
def test_blank_input_reports_nothing(fragment: str) -> None:
    parser = StreamingJsonParser()

    assert parser.feed(fragment) == {}
    assert parser.snapshot() == {}


@pytest.mark.parametrize(
    "document",
    [
        "{a",
        '{"a" 1',
        '{"a": "\\q"}',
        '{"a": "\\uZZZZ"}',
        '{"a": "raw\nnewline"}',
        '{"a": "\\ud83d"}',
        '{"a": "\\ude00"}',
    ],
)
def test_invalid_json_raises_value_error(document: str) -> None:
    with pytest.raises(ValueError):
        StreamingJsonParser().feed(document)


def test_text_with_a_lone_surrogate_raises_value_error() -> None:
    with pytest.raises(ValueError):
        StreamingJsonParser().feed('{"a": "' + chr(0xD83D) + '"}')


def test_snapshot_is_independent_of_the_parser() -> None:
    parser = StreamingJsonParser()
    parser.feed('{"code": "ab')
    snapshot = parser.snapshot()
    snapshot["code"] = "changed"

    assert parser.feed('c"}') == {"code": "c"}


def test_random_documents_match_a_complete_parse() -> None:
    rng = random.Random(15188)
    alphabet = ["a", " ", "é", "😀", "\n", '"', "\\", "/", " ", "\x00"]
    for _ in range(300):
        value = {
            f"k{index}": "".join(
                rng.choice(alphabet) for _ in range(rng.randint(0, 12))
            )
            for index in range(rng.randint(1, 3))
        }
        document = json.dumps(value, ensure_ascii=rng.random() < 0.5)
        cuts = sorted(rng.sample(range(1, len(document)), min(4, len(document) - 1)))
        chunks = [
            document[start:end]
            for start, end in zip([0, *cuts], [*cuts, None], strict=True)
        ]

        joined, parser = _stream(chunks)

        assert parser.snapshot() == value
        assert {key: text for key, text in joined.items() if text} == {
            key: text for key, text in value.items() if text
        }
