from typing import Any
from unittest.mock import MagicMock
from unittest.mock import patch

from onyx.chat.tool_call_args_streaming import maybe_emit_argument_delta
from onyx.server.query_and_chat.placement import Placement
from onyx.server.query_and_chat.streaming_models import ToolCallArgumentDelta
from onyx.utils.jsonriver import Parser


def _make_tool_call_delta(
    index: int = 0,
    name: str | None = None,
    arguments: str | None = None,
    function_is_none: bool = False,
) -> MagicMock:
    """Create a mock tool_call_delta matching the LiteLLM streaming shape."""
    delta = MagicMock()
    delta.index = index
    if function_is_none:
        delta.function = None
    else:
        delta.function = MagicMock()
        delta.function.name = name
        delta.function.arguments = arguments
    return delta


def _make_placement() -> Placement:
    return Placement(turn_index=0, tab_index=0)


def _mock_tool_class(emit: bool = True) -> MagicMock:
    cls = MagicMock()
    cls.should_emit_argument_deltas.return_value = emit
    return cls


def _collect(
    tc_map: dict[int, dict[str, Any]],
    delta: MagicMock,
    placement: Placement | None = None,
    parsers: dict[int, Parser] | None = None,
) -> list[Any]:
    """Run maybe_emit_argument_delta and return the yielded packets."""
    return list(
        maybe_emit_argument_delta(
            tc_map,
            delta,
            placement or _make_placement(),
            parsers if parsers is not None else {},
        )
    )


def _stream_fragments(
    fragments: list[str],
    tc_map: dict[int, dict[str, Any]],
    placement: Placement | None = None,
) -> list[str]:
    """Feed fragments into maybe_emit_argument_delta one by one, returning
    all emitted content values concatenated per-key as a flat list."""
    pl = placement or _make_placement()
    parsers: dict[int, Parser] = {}
    emitted: list[str] = []
    for frag in fragments:
        tc_map[0]["arguments"] += frag
        delta = _make_tool_call_delta(arguments=frag)
        for packet in maybe_emit_argument_delta(tc_map, delta, pl, parsers=parsers):
            obj = packet.obj
            assert isinstance(obj, ToolCallArgumentDelta)
            for value in obj.argument_deltas.values():
                emitted.append(value)
    return emitted


class TestMaybeEmitArgumentDeltaGuards:
    """Tests for conditions that cause no packet to be emitted."""

    @patch("onyx.chat.tool_call_args_streaming._get_tool_class")
    def test_no_emission_when_tool_does_not_opt_in(
        self, mock_get_tool: MagicMock
    ) -> None:
        """Tools that return False from should_emit_argument_deltas emit nothing."""
        mock_get_tool.return_value = _mock_tool_class(emit=False)

        tc_map: dict[int, dict[str, Any]] = {
            0: {"id": "tc_1", "name": "python", "arguments": '{"code": "x'}
        }
        assert _collect(tc_map, _make_tool_call_delta(arguments="x")) == []

    @patch("onyx.chat.tool_call_args_streaming._get_tool_class")
    def test_no_emission_when_tool_class_unknown(
        self, mock_get_tool: MagicMock
    ) -> None:
        mock_get_tool.return_value = None

        tc_map: dict[int, dict[str, Any]] = {
            0: {"id": "tc_1", "name": "unknown", "arguments": '{"code": "x'}
        }
        assert _collect(tc_map, _make_tool_call_delta(arguments="x")) == []

    @patch("onyx.chat.tool_call_args_streaming._get_tool_class")
    def test_no_emission_when_no_argument_fragment(
        self, mock_get_tool: MagicMock
    ) -> None:
        mock_get_tool.return_value = _mock_tool_class()

        tc_map: dict[int, dict[str, Any]] = {
            0: {"id": "tc_1", "name": "python", "arguments": '{"code": "x'}
        }
        assert _collect(tc_map, _make_tool_call_delta(arguments=None)) == []

    @patch("onyx.chat.tool_call_args_streaming._get_tool_class")
    def test_no_emission_when_key_value_not_started(
        self, mock_get_tool: MagicMock
    ) -> None:
        """Key exists in JSON but its string value hasn't begun yet."""
        mock_get_tool.return_value = _mock_tool_class()

        tc_map: dict[int, dict[str, Any]] = {
            0: {"id": "tc_1", "name": "python", "arguments": '{"code":'}
        }
        assert _collect(tc_map, _make_tool_call_delta(arguments=":")) == []

    @patch("onyx.chat.tool_call_args_streaming._get_tool_class")
    def test_no_emission_before_any_key(self, mock_get_tool: MagicMock) -> None:
        """Only the opening brace has arrived — no key to stream yet."""
        mock_get_tool.return_value = _mock_tool_class()

        tc_map: dict[int, dict[str, Any]] = {
            0: {"id": "tc_1", "name": "python", "arguments": "{"}
        }
        assert _collect(tc_map, _make_tool_call_delta(arguments="{")) == []


class TestMaybeEmitArgumentDeltaBasic:
    """Tests for correct packet content and incremental emission."""

    @patch("onyx.chat.tool_call_args_streaming._get_tool_class")
    def test_emits_packet_with_correct_fields(self, mock_get_tool: MagicMock) -> None:
        mock_get_tool.return_value = _mock_tool_class()

        tc_map: dict[int, dict[str, Any]] = {
            0: {"id": "tc_1", "name": "python", "arguments": ""}
        }
        fragments = ['{"code": "', "print(1)", '"}']

        pl = _make_placement()
        parsers: dict[int, Parser] = {}
        all_packets = []
        for frag in fragments:
            tc_map[0]["arguments"] += frag
            packets = _collect(
                tc_map, _make_tool_call_delta(arguments=frag), pl, parsers
            )
            all_packets.extend(packets)

        assert len(all_packets) >= 1
        # Verify packet structure
        obj = all_packets[0].obj
        assert isinstance(obj, ToolCallArgumentDelta)
        assert obj.tool_type == "python"
        # All emitted content should reconstruct the value
        full_code = ""
        for p in all_packets:
            assert isinstance(p.obj, ToolCallArgumentDelta)
            if "code" in p.obj.argument_deltas:
                full_code += p.obj.argument_deltas["code"]
        assert full_code == "print(1)"

    @patch("onyx.chat.tool_call_args_streaming._get_tool_class")
    def test_emits_only_new_content_on_subsequent_call(
        self, mock_get_tool: MagicMock
    ) -> None:
        """After a first emission, subsequent calls emit only the diff."""
        mock_get_tool.return_value = _mock_tool_class()

        tc_map: dict[int, dict[str, Any]] = {
            0: {"id": "tc_1", "name": "python", "arguments": ""}
        }
        parsers: dict[int, Parser] = {}
        pl = _make_placement()

        # First fragment opens the string
        tc_map[0]["arguments"] = '{"code": "abc'
        packets_1 = _collect(
            tc_map, _make_tool_call_delta(arguments='{"code": "abc'), pl, parsers
        )
        code_1 = ""
        for p in packets_1:
            assert isinstance(p.obj, ToolCallArgumentDelta)
            code_1 += p.obj.argument_deltas.get("code", "")
        assert code_1 == "abc"

        # Second fragment appends more
        tc_map[0]["arguments"] = '{"code": "abcdef'
        packets_2 = _collect(
            tc_map, _make_tool_call_delta(arguments="def"), pl, parsers
        )
        code_2 = ""
        for p in packets_2:
            assert isinstance(p.obj, ToolCallArgumentDelta)
            code_2 += p.obj.argument_deltas.get("code", "")
        assert code_2 == "def"

    @patch("onyx.chat.tool_call_args_streaming._get_tool_class")
    def test_handles_multiple_keys_sequentially(self, mock_get_tool: MagicMock) -> None:
        """When a second key starts, emissions switch to that key."""
        mock_get_tool.return_value = _mock_tool_class()

        tc_map: dict[int, dict[str, Any]] = {
            0: {"id": "tc_1", "name": "python", "arguments": ""}
        }
        fragments = [
            '{"code": "x',
            '", "output": "hello',
            '"}',
        ]

        emitted = _stream_fragments(fragments, tc_map)
        full = "".join(emitted)
        assert "x" in full
        assert "hello" in full

    @patch("onyx.chat.tool_call_args_streaming._get_tool_class")
    def test_delta_spans_key_boundary(self, mock_get_tool: MagicMock) -> None:
        """A single delta contains the end of one value and the start of the next key."""
        mock_get_tool.return_value = _mock_tool_class()

        tc_map: dict[int, dict[str, Any]] = {
            0: {"id": "tc_1", "name": "python", "arguments": ""}
        }
        fragments = [
            '{"code": "x',
            'y", "lang": "py',
            '"}',
        ]

        emitted = _stream_fragments(fragments, tc_map)
        full = "".join(emitted)
        assert "xy" in full
        assert "py" in full

    @patch("onyx.chat.tool_call_args_streaming._get_tool_class")
    def test_empty_value_emits_nothing(self, mock_get_tool: MagicMock) -> None:
        """An empty string value has nothing to emit."""
        mock_get_tool.return_value = _mock_tool_class()

        tc_map: dict[int, dict[str, Any]] = {
            0: {"id": "tc_1", "name": "python", "arguments": ""}
        }
        # Opening quote just arrived, value is empty
        tc_map[0]["arguments"] = '{"code": "'
        packets = _collect(tc_map, _make_tool_call_delta(arguments='{"code": "'))
        # No string content yet, so either no packet or empty deltas
        for p in packets:
            assert isinstance(p.obj, ToolCallArgumentDelta)
            assert p.obj.argument_deltas.get("code", "") == ""


class TestMaybeEmitArgumentDeltaDecoding:
    """Tests verifying that JSON escape sequences are properly decoded."""

    @patch("onyx.chat.tool_call_args_streaming._get_tool_class")
    def test_decodes_newlines(self, mock_get_tool: MagicMock) -> None:
        mock_get_tool.return_value = _mock_tool_class()

        tc_map: dict[int, dict[str, Any]] = {
            0: {"id": "tc_1", "name": "python", "arguments": ""}
        }
        fragments = ['{"code": "line1\\nline2"}']

        emitted = _stream_fragments(fragments, tc_map)
        assert "".join(emitted) == "line1\nline2"

    @patch("onyx.chat.tool_call_args_streaming._get_tool_class")
    def test_decodes_tabs(self, mock_get_tool: MagicMock) -> None:
        mock_get_tool.return_value = _mock_tool_class()

        tc_map: dict[int, dict[str, Any]] = {
            0: {"id": "tc_1", "name": "python", "arguments": ""}
        }
        fragments = ['{"code": "\\tindented"}']

        emitted = _stream_fragments(fragments, tc_map)
        assert "".join(emitted) == "\tindented"

    @patch("onyx.chat.tool_call_args_streaming._get_tool_class")
    def test_decodes_escaped_quotes(self, mock_get_tool: MagicMock) -> None:
        mock_get_tool.return_value = _mock_tool_class()

        tc_map: dict[int, dict[str, Any]] = {
            0: {"id": "tc_1", "name": "python", "arguments": ""}
        }
        fragments = ['{"code": "say \\"hi\\""}']

        emitted = _stream_fragments(fragments, tc_map)
        assert "".join(emitted) == 'say "hi"'

    @patch("onyx.chat.tool_call_args_streaming._get_tool_class")
    def test_decodes_escaped_backslashes(self, mock_get_tool: MagicMock) -> None:
        mock_get_tool.return_value = _mock_tool_class()

        tc_map: dict[int, dict[str, Any]] = {
            0: {"id": "tc_1", "name": "python", "arguments": ""}
        }
        fragments = ['{"code": "path\\\\dir"}']

        emitted = _stream_fragments(fragments, tc_map)
        assert "".join(emitted) == "path\\dir"

    @patch("onyx.chat.tool_call_args_streaming._get_tool_class")
    def test_decodes_unicode_escape(self, mock_get_tool: MagicMock) -> None:
        mock_get_tool.return_value = _mock_tool_class()

        tc_map: dict[int, dict[str, Any]] = {
            0: {"id": "tc_1", "name": "python", "arguments": ""}
        }
        fragments = ['{"code": "\\u0041"}']

        emitted = _stream_fragments(fragments, tc_map)
        assert "".join(emitted) == "A"

    @patch("onyx.chat.tool_call_args_streaming._get_tool_class")
    def test_incomplete_escape_at_end_decoded_on_next_chunk(
        self, mock_get_tool: MagicMock
    ) -> None:
        """A trailing backslash (incomplete escape) is completed in the next chunk."""
        mock_get_tool.return_value = _mock_tool_class()

        tc_map: dict[int, dict[str, Any]] = {
            0: {"id": "tc_1", "name": "python", "arguments": ""}
        }
        fragments = ['{"code": "hello\\', 'n"}']

        emitted = _stream_fragments(fragments, tc_map)
        assert "".join(emitted) == "hello\n"

    @patch("onyx.chat.tool_call_args_streaming._get_tool_class")
    def test_incomplete_unicode_escape_completed_on_next_chunk(
        self, mock_get_tool: MagicMock
    ) -> None:
        """A partial \\uXX sequence is completed in the next chunk."""
        mock_get_tool.return_value = _mock_tool_class()

        tc_map: dict[int, dict[str, Any]] = {
            0: {"id": "tc_1", "name": "python", "arguments": ""}
        }
        fragments = ['{"code": "hello\\u00', '41"}']

        emitted = _stream_fragments(fragments, tc_map)
        assert "".join(emitted) == "helloA"


class TestArgumentDeltaStreamingE2E:
    """Simulates realistic sequences of LLM argument deltas to verify
    the full pipeline produces correct decoded output."""

    @patch("onyx.chat.tool_call_args_streaming._get_tool_class")
    def test_realistic_python_code_streaming(self, mock_get_tool: MagicMock) -> None:
        """Streams: {"code": "print('hello')\\nprint('world')"}"""
        mock_get_tool.return_value = _mock_tool_class()

        tc_map: dict[int, dict[str, Any]] = {
            0: {"id": "tc_1", "name": "python", "arguments": ""}
        }
        fragments = [
            '{"',
            "code",
            '": "',
            "print(",
            "'hello')",
            "\\n",
            "print(",
            "'world')",
            '"}',
        ]

        full = "".join(_stream_fragments(fragments, tc_map))
        assert full == "print('hello')\nprint('world')"

    @patch("onyx.chat.tool_call_args_streaming._get_tool_class")
    def test_streaming_with_tabs_and_newlines(self, mock_get_tool: MagicMock) -> None:
        """Streams code with tabs and newlines."""
        mock_get_tool.return_value = _mock_tool_class()

        tc_map: dict[int, dict[str, Any]] = {
            0: {"id": "tc_1", "name": "python", "arguments": ""}
        }
        fragments = [
            '{"code": "',
            "if True:",
            "\\n",
            "\\t",
            "pass",
            '"}',
        ]

        full = "".join(_stream_fragments(fragments, tc_map))
        assert full == "if True:\n\tpass"

    @patch("onyx.chat.tool_call_args_streaming._get_tool_class")
    def test_split_escape_sequence(self, mock_get_tool: MagicMock) -> None:
        """An escape sequence split across two fragments (backslash in one,
        'n' in the next) should still decode correctly."""
        mock_get_tool.return_value = _mock_tool_class()

        tc_map: dict[int, dict[str, Any]] = {
            0: {"id": "tc_1", "name": "python", "arguments": ""}
        }
        fragments = [
            '{"code": "hello',
            "\\",
            "n",
            'world"}',
        ]

        full = "".join(_stream_fragments(fragments, tc_map))
        assert full == "hello\nworld"

    @patch("onyx.chat.tool_call_args_streaming._get_tool_class")
    def test_multiple_newlines_and_indentation(self, mock_get_tool: MagicMock) -> None:
        """Streams a multi-line function with multiple escape sequences."""
        mock_get_tool.return_value = _mock_tool_class()

        tc_map: dict[int, dict[str, Any]] = {
            0: {"id": "tc_1", "name": "python", "arguments": ""}
        }
        fragments = [
            '{"code": "',
            "def foo():",
            "\\n",
            "\\t",
            "x = 1",
            "\\n",
            "\\t",
            "return x",
            '"}',
        ]

        full = "".join(_stream_fragments(fragments, tc_map))
        assert full == "def foo():\n\tx = 1\n\treturn x"

    @patch("onyx.chat.tool_call_args_streaming._get_tool_class")
    def test_two_keys_streamed_sequentially(self, mock_get_tool: MagicMock) -> None:
        """Streams code first, then a second key (language) — both decoded."""
        mock_get_tool.return_value = _mock_tool_class()

        tc_map: dict[int, dict[str, Any]] = {
            0: {"id": "tc_1", "name": "python", "arguments": ""}
        }
        fragments = [
            '{"code": "',
            "x = 1",
            '", "language": "',
            "python",
            '"}',
        ]

        emitted = _stream_fragments(fragments, tc_map)
        # Should have emissions for both keys
        full = "".join(emitted)
        assert "x = 1" in full
        assert "python" in full

    @patch("onyx.chat.tool_call_args_streaming._get_tool_class")
    def test_code_containing_dict_literal(self, mock_get_tool: MagicMock) -> None:
        """Python code like `x = {"key": "val"}` contains JSON-like patterns.
        The escaped quotes inside the *outer* JSON value should prevent the
        inner `"key":` from being mistaken for a top-level JSON key."""
        mock_get_tool.return_value = _mock_tool_class()

        tc_map: dict[int, dict[str, Any]] = {
            0: {"id": "tc_1", "name": "python", "arguments": ""}
        }
        # The LLM sends: {"code": "x = {\"key\": \"val\"}"}
        # The inner quotes are escaped as \" in the JSON value.
        fragments = [
            '{"code": "',
            "x = {",
            '\\"key\\"',
            ": ",
            '\\"val\\"',
            "}",
            '"}',
        ]

        full = "".join(_stream_fragments(fragments, tc_map))
        assert full == 'x = {"key": "val"}'

    @patch("onyx.chat.tool_call_args_streaming._get_tool_class")
    def test_code_with_colon_in_value(self, mock_get_tool: MagicMock) -> None:
        """Colons inside the string value should not confuse key detection."""
        mock_get_tool.return_value = _mock_tool_class()

        tc_map: dict[int, dict[str, Any]] = {
            0: {"id": "tc_1", "name": "python", "arguments": ""}
        }
        fragments = [
            '{"code": "',
            "url = ",
            '\\"https://example.com\\"',
            '"}',
        ]

        full = "".join(_stream_fragments(fragments, tc_map))
        assert full == 'url = "https://example.com"'


class TestMaybeEmitArgumentDeltaEdgeCases:
    """Edge cases not covered by the standard test classes."""

    @patch("onyx.chat.tool_call_args_streaming._get_tool_class")
    def test_no_emission_when_function_is_none(self, mock_get_tool: MagicMock) -> None:
        """Some delta chunks have function=None (e.g. role-only deltas)."""
        mock_get_tool.return_value = _mock_tool_class()

        tc_map: dict[int, dict[str, Any]] = {
            0: {"id": "tc_1", "name": "python", "arguments": '{"code": "x'}
        }
        delta = _make_tool_call_delta(arguments=None, function_is_none=True)
        assert _collect(tc_map, delta) == []

    @patch("onyx.chat.tool_call_args_streaming._get_tool_class")
    def test_multiple_concurrent_tool_calls(self, mock_get_tool: MagicMock) -> None:
        """Two tool calls streaming at different indices in parallel."""
        mock_get_tool.return_value = _mock_tool_class()

        tc_map: dict[int, dict[str, Any]] = {
            0: {"id": "tc_1", "name": "python", "arguments": ""},
            1: {"id": "tc_2", "name": "python", "arguments": ""},
        }

        parsers: dict[int, Parser] = {}
        pl = _make_placement()

        # Feed full JSON to index 0
        tc_map[0]["arguments"] = '{"code": "aaa"}'
        packets_0 = _collect(
            tc_map,
            _make_tool_call_delta(index=0, arguments='{"code": "aaa"}'),
            pl,
            parsers,
        )
        code_0 = ""
        for p in packets_0:
            assert isinstance(p.obj, ToolCallArgumentDelta)
            code_0 += p.obj.argument_deltas.get("code", "")
        assert code_0 == "aaa"

        # Feed full JSON to index 1
        tc_map[1]["arguments"] = '{"code": "bbb"}'
        packets_1 = _collect(
            tc_map,
            _make_tool_call_delta(index=1, arguments='{"code": "bbb"}'),
            pl,
            parsers,
        )
        code_1 = ""
        for p in packets_1:
            assert isinstance(p.obj, ToolCallArgumentDelta)
            code_1 += p.obj.argument_deltas.get("code", "")
        assert code_1 == "bbb"

    @patch("onyx.chat.tool_call_args_streaming._get_tool_class")
    def test_delta_with_four_arguments(self, mock_get_tool: MagicMock) -> None:
        """A single delta contains four complete key-value pairs."""
        mock_get_tool.return_value = _mock_tool_class()

        full = '{"a": "one", "b": "two", "c": "three", "d": "four"}'
        tc_map: dict[int, dict[str, Any]] = {
            0: {"id": "tc_1", "name": "python", "arguments": ""}
        }
        tc_map[0]["arguments"] = full
        parsers: dict[int, Parser] = {}
        packets = _collect(
            tc_map, _make_tool_call_delta(arguments=full), parsers=parsers
        )

        # Collect all argument deltas across packets
        all_deltas: dict[str, str] = {}
        for p in packets:
            assert isinstance(p.obj, ToolCallArgumentDelta)
            for k, v in p.obj.argument_deltas.items():
                all_deltas[k] = all_deltas.get(k, "") + v

        assert all_deltas == {
            "a": "one",
            "b": "two",
            "c": "three",
            "d": "four",
        }

    @patch("onyx.chat.tool_call_args_streaming._get_tool_class")
    def test_delta_on_second_arg_after_first_complete(
        self, mock_get_tool: MagicMock
    ) -> None:
        """First argument is fully complete; delta only adds to the second."""
        mock_get_tool.return_value = _mock_tool_class()

        tc_map: dict[int, dict[str, Any]] = {
            0: {"id": "tc_1", "name": "python", "arguments": ""}
        }

        fragments = [
            '{"code": "print(1)", "lang": "py',
            '"}',
        ]

        emitted = _stream_fragments(fragments, tc_map)
        full = "".join(emitted)
        assert "print(1)" in full
        assert "py" in full

    @patch("onyx.chat.tool_call_args_streaming._get_tool_class")
    def test_non_string_values_skipped(self, mock_get_tool: MagicMock) -> None:
        """Non-string values (numbers, booleans, null) are skipped — they are
        available in the final tool-call kickoff packet. String arguments
        following them are still emitted."""
        mock_get_tool.return_value = _mock_tool_class()

        tc_map: dict[int, dict[str, Any]] = {
            0: {"id": "tc_1", "name": "python", "arguments": ""}
        }
        fragments = ['{"timeout": 30, "code": "hello"}']

        emitted = _stream_fragments(fragments, tc_map)
        full = "".join(emitted)
        assert full == "hello"
