"""Tests for the jsonriver incremental JSON parser."""

import json

import pytest

from onyx.utils.jsonriver import JsonValue
from onyx.utils.jsonriver import Parser


def _all_deltas(chunks: list[str]) -> list[JsonValue]:
    """Feed chunks one at a time and collect all emitted deltas."""
    parser = Parser()
    deltas: list[JsonValue] = []
    for chunk in chunks:
        deltas.extend(parser.feed(chunk))
    deltas.extend(parser.finish())
    return deltas


class TestParseComplete:
    """Parsing complete JSON in a single chunk."""

    def test_simple_object(self) -> None:
        deltas = _all_deltas(['{"a": 1}'])
        assert any(r == {"a": 1.0} or r == {"a": 1} for r in deltas)

    def test_simple_array(self) -> None:
        deltas = _all_deltas(["[1, 2, 3]"])
        assert any(isinstance(r, list) for r in deltas)

    def test_simple_string(self) -> None:
        deltas = _all_deltas(['"hello"'])
        assert "hello" in deltas or any("hello" in str(r) for r in deltas)

    def test_null(self) -> None:
        deltas = _all_deltas(["null"])
        assert None in deltas

    def test_boolean_true(self) -> None:
        deltas = _all_deltas(["true"])
        assert True in deltas

    def test_boolean_false(self) -> None:
        deltas = _all_deltas(["false"])
        assert any(r is False for r in deltas)

    def test_number(self) -> None:
        deltas = _all_deltas(["42"])
        assert 42.0 in deltas

    def test_negative_number(self) -> None:
        deltas = _all_deltas(["-3.14"])
        assert any(abs(r - (-3.14)) < 1e-10 for r in deltas if isinstance(r, float))

    def test_empty_object(self) -> None:
        deltas = _all_deltas(["{}"])
        assert {} in deltas

    def test_empty_array(self) -> None:
        deltas = _all_deltas(["[]"])
        assert [] in deltas


class TestStreamingDeltas:
    """Incremental feeding produces correct deltas."""

    def test_object_string_value_streamed_char_by_char(self) -> None:
        chunks = list('{"code": "abc"}')
        deltas = _all_deltas(chunks)
        str_parts = []
        for d in deltas:
            if isinstance(d, dict) and "code" in d:
                val = d["code"]
                if isinstance(val, str):
                    str_parts.append(val)
        assert "".join(str_parts) == "abc"

    def test_object_streamed_in_two_halves(self) -> None:
        deltas = _all_deltas(['{"name": "Al', 'ice"}'])
        str_parts = []
        for d in deltas:
            if isinstance(d, dict) and "name" in d:
                val = d["name"]
                if isinstance(val, str):
                    str_parts.append(val)
        assert "".join(str_parts) == "Alice"

    def test_multiple_keys_streamed(self) -> None:
        deltas = _all_deltas(['{"a": "x', '", "b": "y"}'])
        a_parts: list[str] = []
        b_parts: list[str] = []
        for d in deltas:
            if isinstance(d, dict):
                if "a" in d and isinstance(d["a"], str):
                    a_parts.append(d["a"])
                if "b" in d and isinstance(d["b"], str):
                    b_parts.append(d["b"])
        assert "".join(a_parts) == "x"
        assert "".join(b_parts) == "y"

    def test_deltas_only_contain_new_string_content(self) -> None:
        parser = Parser()
        d1 = parser.feed('{"msg": "hel')
        d2 = parser.feed('lo"}')
        parser.finish()

        msg_parts = []
        for d in d1 + d2:
            if isinstance(d, dict) and "msg" in d:
                val = d["msg"]
                if isinstance(val, str):
                    msg_parts.append(val)
        assert "".join(msg_parts) == "hello"

        # Each delta should only contain new chars, not repeat previous ones
        if len(msg_parts) == 2:
            assert msg_parts[0] == "hel"
            assert msg_parts[1] == "lo"


class TestEscapeSequences:
    """JSON escape sequences are decoded correctly, even across chunk boundaries."""

    def test_newline_escape(self) -> None:
        deltas = _all_deltas(['{"text": "line1\\nline2"}'])
        text_parts = []
        for d in deltas:
            if isinstance(d, dict) and "text" in d and isinstance(d["text"], str):
                text_parts.append(d["text"])
        assert "".join(text_parts) == "line1\nline2"

    def test_tab_escape(self) -> None:
        deltas = _all_deltas(['{"t": "a\\tb"}'])
        parts = []
        for d in deltas:
            if isinstance(d, dict) and "t" in d and isinstance(d["t"], str):
                parts.append(d["t"])
        assert "".join(parts) == "a\tb"

    def test_escaped_quote(self) -> None:
        deltas = _all_deltas(['{"q": "say \\"hi\\""}'])
        parts = []
        for d in deltas:
            if isinstance(d, dict) and "q" in d and isinstance(d["q"], str):
                parts.append(d["q"])
        assert "".join(parts) == 'say "hi"'

    def test_unicode_escape(self) -> None:
        deltas = _all_deltas(['{"u": "\\u0041\\u0042"}'])
        parts = []
        for d in deltas:
            if isinstance(d, dict) and "u" in d and isinstance(d["u"], str):
                parts.append(d["u"])
        assert "".join(parts) == "AB"

    def test_escape_split_across_chunks(self) -> None:
        deltas = _all_deltas(['{"x": "a\\', 'nb"}'])
        parts = []
        for d in deltas:
            if isinstance(d, dict) and "x" in d and isinstance(d["x"], str):
                parts.append(d["x"])
        assert "".join(parts) == "a\nb"

    def test_unicode_escape_split_across_chunks(self) -> None:
        deltas = _all_deltas(['{"u": "\\u00', '41"}'])
        parts = []
        for d in deltas:
            if isinstance(d, dict) and "u" in d and isinstance(d["u"], str):
                parts.append(d["u"])
        assert "".join(parts) == "A"

    def test_backslash_escape(self) -> None:
        deltas = _all_deltas(['{"p": "c:\\\\dir"}'])
        parts = []
        for d in deltas:
            if isinstance(d, dict) and "p" in d and isinstance(d["p"], str):
                parts.append(d["p"])
        assert "".join(parts) == "c:\\dir"


class TestNestedStructures:
    """Nested objects and arrays produce correct deltas."""

    def test_nested_object(self) -> None:
        deltas = _all_deltas(['{"outer": {"inner": "val"}}'])
        found = False
        for d in deltas:
            if isinstance(d, dict) and "outer" in d:
                outer = d["outer"]
                if isinstance(outer, dict) and "inner" in outer:
                    found = True
        assert found

    def test_array_of_strings(self) -> None:
        deltas = _all_deltas(['["a', '", "b"]'])
        all_items: list[str] = []
        for d in deltas:
            if isinstance(d, list):
                for item in d:
                    if isinstance(item, str):
                        all_items.append(item)
            elif isinstance(d, str):
                all_items.append(d)
        joined = "".join(all_items)
        assert "a" in joined
        assert "b" in joined

    def test_object_with_number_and_bool(self) -> None:
        deltas = _all_deltas(['{"count": 42, "active": true}'])
        has_count = False
        has_active = False
        for d in deltas:
            if isinstance(d, dict):
                if "count" in d and d["count"] == 42.0:
                    has_count = True
                if "active" in d and d["active"] is True:
                    has_active = True
        assert has_count
        assert has_active

    def test_object_with_null_value(self) -> None:
        deltas = _all_deltas(['{"key": null}'])
        found = False
        for d in deltas:
            if isinstance(d, dict) and "key" in d and d["key"] is None:
                found = True
        assert found


class TestComputeDelta:
    """Direct tests for the _compute_delta static method."""

    def test_none_prev_returns_current(self) -> None:
        assert Parser._compute_delta(None, {"a": "b"}) == {"a": "b"}

    def test_string_delta(self) -> None:
        assert Parser._compute_delta("hel", "hello") == "lo"

    def test_string_no_change(self) -> None:
        assert Parser._compute_delta("same", "same") is None

    def test_dict_new_key(self) -> None:
        assert Parser._compute_delta({"a": "x"}, {"a": "x", "b": "y"}) == {"b": "y"}

    def test_dict_string_append(self) -> None:
        assert Parser._compute_delta({"code": "def"}, {"code": "def hello()"}) == {
            "code": " hello()"
        }

    def test_dict_no_change(self) -> None:
        assert Parser._compute_delta({"a": 1}, {"a": 1}) is None

    def test_list_new_items(self) -> None:
        assert Parser._compute_delta([1, 2], [1, 2, 3]) == [3]

    def test_list_last_item_updated(self) -> None:
        assert Parser._compute_delta(["a"], ["ab"]) == ["ab"]

    def test_list_no_change(self) -> None:
        assert Parser._compute_delta([1, 2], [1, 2]) is None

    def test_primitive_change(self) -> None:
        assert Parser._compute_delta(1, 2) == 2

    def test_primitive_no_change(self) -> None:
        assert Parser._compute_delta(42, 42) is None


class TestParserLifecycle:
    """Edge cases around parser state and lifecycle."""

    def test_feed_after_finish_returns_empty(self) -> None:
        parser = Parser()
        parser.feed('{"a": 1}')
        parser.finish()
        assert parser.feed("more") == []

    def test_empty_feed_returns_empty(self) -> None:
        parser = Parser()
        assert parser.feed("") == []

    def test_whitespace_only_returns_empty(self) -> None:
        parser = Parser()
        assert parser.feed("   ") == []

    def test_finish_with_trailing_whitespace(self) -> None:
        parser = Parser()
        # Trailing whitespace terminates the number, so feed() emits it
        deltas = parser.feed("42  ")
        assert 42.0 in deltas
        parser.finish()  # Should not raise

    def test_finish_with_trailing_content_raises(self) -> None:
        parser = Parser()
        # Feed a complete JSON value followed by non-whitespace in one chunk
        parser.feed('{"a": 1} extra')
        with pytest.raises(ValueError, match="Unexpected trailing"):
            parser.finish()

    def test_finish_flushes_pending_number(self) -> None:
        parser = Parser()
        deltas = parser.feed("42")
        # Number has no terminator, so feed() can't emit it yet
        assert deltas == []
        final = parser.finish()
        assert 42.0 in final


class TestToolCallSimulation:
    """Simulate the LLM tool-call streaming use case."""

    def test_python_tool_call_streaming(self) -> None:
        full_json = json.dumps({"code": "print('hello world')"})
        chunk_size = 5
        chunks = [
            full_json[i : i + chunk_size] for i in range(0, len(full_json), chunk_size)
        ]

        parser = Parser()
        code_parts: list[str] = []
        for chunk in chunks:
            for delta in parser.feed(chunk):
                if isinstance(delta, dict) and "code" in delta:
                    val = delta["code"]
                    if isinstance(val, str):
                        code_parts.append(val)
        for delta in parser.finish():
            if isinstance(delta, dict) and "code" in delta:
                val = delta["code"]
                if isinstance(val, str):
                    code_parts.append(val)
        assert "".join(code_parts) == "print('hello world')"

    def test_multi_arg_tool_call(self) -> None:
        full = '{"query": "search term", "num_results": 5}'
        chunks = [full[:15], full[15:30], full[30:]]

        parser = Parser()
        query_parts: list[str] = []
        has_num_results = False
        for chunk in chunks:
            for delta in parser.feed(chunk):
                if isinstance(delta, dict):
                    if "query" in delta and isinstance(delta["query"], str):
                        query_parts.append(delta["query"])
                    if "num_results" in delta:
                        has_num_results = True
        for delta in parser.finish():
            if isinstance(delta, dict):
                if "query" in delta and isinstance(delta["query"], str):
                    query_parts.append(delta["query"])
                if "num_results" in delta:
                    has_num_results = True
        assert "".join(query_parts) == "search term"
        assert has_num_results

    def test_code_with_newlines_and_escapes(self) -> None:
        code = 'def greet(name):\n    print(f"Hello, {name}!")\n    return True'
        full = json.dumps({"code": code})
        chunk_size = 8
        chunks = [full[i : i + chunk_size] for i in range(0, len(full), chunk_size)]

        parser = Parser()
        code_parts: list[str] = []
        for chunk in chunks:
            for delta in parser.feed(chunk):
                if isinstance(delta, dict) and "code" in delta:
                    val = delta["code"]
                    if isinstance(val, str):
                        code_parts.append(val)
        for delta in parser.finish():
            if isinstance(delta, dict) and "code" in delta:
                val = delta["code"]
                if isinstance(val, str):
                    code_parts.append(val)
        assert "".join(code_parts) == code

    def test_single_char_streaming(self) -> None:
        full = '{"key": "value"}'
        parser = Parser()
        key_parts: list[str] = []
        for ch in full:
            for delta in parser.feed(ch):
                if isinstance(delta, dict) and "key" in delta:
                    val = delta["key"]
                    if isinstance(val, str):
                        key_parts.append(val)
        for delta in parser.finish():
            if isinstance(delta, dict) and "key" in delta:
                val = delta["key"]
                if isinstance(val, str):
                    key_parts.append(val)
        assert "".join(key_parts) == "value"
