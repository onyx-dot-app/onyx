from __future__ import annotations

from onyx.utils.text_processing import parse_llm_json_response


def test_parses_plain_object() -> None:
    assert parse_llm_json_response('{"sources": ["zendesk"]}') == {
        "sources": ["zendesk"]
    }


def test_parses_object_in_markdown_code_block() -> None:
    content = '```json\n{"sources": ["zendesk"]}\n```'
    assert parse_llm_json_response(content) == {"sources": ["zendesk"]}


def test_parses_object_with_surrounding_prose() -> None:
    content = 'Here you go: {"sources": ["zendesk"]} hope that helps'
    assert parse_llm_json_response(content) == {"sources": ["zendesk"]}


def test_duplicate_object_returns_first() -> None:
    """Regression: some models emit the object twice; the greedy first-to-last
    brace match can't parse `{...}{...}`, so the first object must still win."""
    content = '{"sources":["zendesk"]}{"sources":["zendesk"]}'
    assert parse_llm_json_response(content) == {"sources": ["zendesk"]}


def test_trailing_garbage_after_object() -> None:
    content = '{"sources":["zendesk"]} and then some junk {not json'
    assert parse_llm_json_response(content) == {"sources": ["zendesk"]}


def test_nested_object_preserved() -> None:
    content = '{"a": {"b": 1}} {"a": {"b": 2}}'
    assert parse_llm_json_response(content) == {"a": {"b": 1}}


def test_non_json_returns_none() -> None:
    assert parse_llm_json_response("no json here") is None
