from onyx.server.query_and_chat.placement import Placement
from onyx.tools.models import ToolCallKickoff
from onyx.tools.tool_runner import _merge_tool_calls


def _make_tool_call(
    tool_name: str,
    tool_args: dict,
    tool_call_id: str = "call_1",
    turn_index: int = 0,
    tab_index: int = 0,
) -> ToolCallKickoff:
    """Helper to create a ToolCallKickoff for testing."""
    return ToolCallKickoff(
        tool_call_id=tool_call_id,
        tool_name=tool_name,
        tool_args=tool_args,
        placement=Placement(turn_index=turn_index, tab_index=tab_index),
    )


class TestMergeToolCalls:
    """Tests for _merge_tool_calls function."""

    def test_empty_list(self) -> None:
        """Empty input returns empty output."""
        result = _merge_tool_calls([])
        assert result == []

    def test_single_search_tool_call_not_merged(self) -> None:
        """A single SearchTool call is returned as-is (no merging needed)."""
        call = _make_tool_call(
            tool_name="internal_search",
            tool_args={"queries": ["query1"]},
            tool_call_id="call_1",
        )
        result = _merge_tool_calls([call])

        assert len(result) == 1
        assert result[0].tool_name == "internal_search"
        assert result[0].tool_args == {"queries": ["query1"]}
        assert result[0].tool_call_id == "call_1"

    def test_single_web_search_tool_call_not_merged(self) -> None:
        """A single WebSearchTool call is returned as-is."""
        call = _make_tool_call(
            tool_name="web_search",
            tool_args={"queries": ["web query"]},
        )
        result = _merge_tool_calls([call])

        assert len(result) == 1
        assert result[0].tool_name == "web_search"
        assert result[0].tool_args == {"queries": ["web query"]}

    def test_single_open_url_tool_call_not_merged(self) -> None:
        """A single OpenURLTool call is returned as-is."""
        call = _make_tool_call(
            tool_name="open_url",
            tool_args={"urls": ["https://example.com"]},
        )
        result = _merge_tool_calls([call])

        assert len(result) == 1
        assert result[0].tool_name == "open_url"
        assert result[0].tool_args == {"urls": ["https://example.com"]}

    def test_multiple_search_tool_calls_merged(self) -> None:
        """Multiple SearchTool calls have their queries merged into one call."""
        calls = [
            _make_tool_call(
                tool_name="internal_search",
                tool_args={"queries": ["query1", "query2"]},
                tool_call_id="call_1",
            ),
            _make_tool_call(
                tool_name="internal_search",
                tool_args={"queries": ["query3"]},
                tool_call_id="call_2",
            ),
        ]
        result = _merge_tool_calls(calls)

        assert len(result) == 1
        assert result[0].tool_name == "internal_search"
        assert result[0].tool_args["queries"] == ["query1", "query2", "query3"]
        # Uses first call's ID
        assert result[0].tool_call_id == "call_1"

    def test_multiple_web_search_tool_calls_merged(self) -> None:
        """Multiple WebSearchTool calls have their queries merged."""
        calls = [
            _make_tool_call(
                tool_name="web_search",
                tool_args={"queries": ["web1"]},
                tool_call_id="call_1",
            ),
            _make_tool_call(
                tool_name="web_search",
                tool_args={"queries": ["web2", "web3"]},
                tool_call_id="call_2",
            ),
        ]
        result = _merge_tool_calls(calls)

        assert len(result) == 1
        assert result[0].tool_name == "web_search"
        assert result[0].tool_args["queries"] == ["web1", "web2", "web3"]

    def test_multiple_open_url_tool_calls_merged(self) -> None:
        """Multiple OpenURLTool calls have their urls merged."""
        calls = [
            _make_tool_call(
                tool_name="open_url",
                tool_args={"urls": ["https://a.com"]},
                tool_call_id="call_1",
            ),
            _make_tool_call(
                tool_name="open_url",
                tool_args={"urls": ["https://b.com", "https://c.com"]},
                tool_call_id="call_2",
            ),
        ]
        result = _merge_tool_calls(calls)

        assert len(result) == 1
        assert result[0].tool_name == "open_url"
        assert result[0].tool_args["urls"] == [
            "https://a.com",
            "https://b.com",
            "https://c.com",
        ]

    def test_non_mergeable_tool_not_merged(self) -> None:
        """Non-mergeable tools (e.g., python) are returned as separate calls."""
        calls = [
            _make_tool_call(
                tool_name="python",
                tool_args={"code": "print(1)"},
                tool_call_id="call_1",
            ),
            _make_tool_call(
                tool_name="python",
                tool_args={"code": "print(2)"},
                tool_call_id="call_2",
            ),
        ]
        result = _merge_tool_calls(calls)

        assert len(result) == 2
        assert result[0].tool_args["code"] == "print(1)"
        assert result[1].tool_args["code"] == "print(2)"

    def test_mixed_mergeable_and_non_mergeable(self) -> None:
        """Mix of mergeable and non-mergeable tools handles correctly."""
        calls = [
            _make_tool_call(
                tool_name="internal_search",
                tool_args={"queries": ["q1"]},
                tool_call_id="search_1",
            ),
            _make_tool_call(
                tool_name="python",
                tool_args={"code": "x = 1"},
                tool_call_id="python_1",
            ),
            _make_tool_call(
                tool_name="internal_search",
                tool_args={"queries": ["q2"]},
                tool_call_id="search_2",
            ),
        ]
        result = _merge_tool_calls(calls)

        # Should have 2 calls: merged search + python
        assert len(result) == 2

        tool_names = {r.tool_name for r in result}
        assert tool_names == {"internal_search", "python"}

        search_result = next(r for r in result if r.tool_name == "internal_search")
        assert search_result.tool_args["queries"] == ["q1", "q2"]

        python_result = next(r for r in result if r.tool_name == "python")
        assert python_result.tool_args["code"] == "x = 1"

    def test_multiple_different_mergeable_tools(self) -> None:
        """Multiple different mergeable tools each get merged separately."""
        calls = [
            _make_tool_call(
                tool_name="internal_search",
                tool_args={"queries": ["search1"]},
            ),
            _make_tool_call(
                tool_name="web_search",
                tool_args={"queries": ["web1"]},
            ),
            _make_tool_call(
                tool_name="internal_search",
                tool_args={"queries": ["search2"]},
            ),
            _make_tool_call(
                tool_name="web_search",
                tool_args={"queries": ["web2"]},
            ),
        ]
        result = _merge_tool_calls(calls)

        # Should have 2 merged calls
        assert len(result) == 2

        search_result = next(r for r in result if r.tool_name == "internal_search")
        assert search_result.tool_args["queries"] == ["search1", "search2"]

        web_result = next(r for r in result if r.tool_name == "web_search")
        assert web_result.tool_args["queries"] == ["web1", "web2"]

    def test_preserves_first_call_placement(self) -> None:
        """Merged call uses the placement from the first call."""
        calls = [
            _make_tool_call(
                tool_name="internal_search",
                tool_args={"queries": ["q1"]},
                turn_index=1,
                tab_index=2,
            ),
            _make_tool_call(
                tool_name="internal_search",
                tool_args={"queries": ["q2"]},
                turn_index=3,
                tab_index=4,
            ),
        ]
        result = _merge_tool_calls(calls)

        assert len(result) == 1
        assert result[0].placement.turn_index == 1
        assert result[0].placement.tab_index == 2

    def test_preserves_other_args_from_first_call(self) -> None:
        """Merged call preserves non-merge-field args from the first call."""
        calls = [
            _make_tool_call(
                tool_name="internal_search",
                tool_args={"queries": ["q1"], "other_param": "value1"},
            ),
            _make_tool_call(
                tool_name="internal_search",
                tool_args={"queries": ["q2"], "other_param": "value2"},
            ),
        ]
        result = _merge_tool_calls(calls)

        assert len(result) == 1
        assert result[0].tool_args["queries"] == ["q1", "q2"]
        # Other params from first call are preserved
        assert result[0].tool_args["other_param"] == "value1"

    def test_handles_empty_queries_list(self) -> None:
        """Handles calls with empty queries lists."""
        calls = [
            _make_tool_call(
                tool_name="internal_search",
                tool_args={"queries": []},
            ),
            _make_tool_call(
                tool_name="internal_search",
                tool_args={"queries": ["q1"]},
            ),
        ]
        result = _merge_tool_calls(calls)

        assert len(result) == 1
        assert result[0].tool_args["queries"] == ["q1"]

    def test_handles_missing_merge_field(self) -> None:
        """Handles calls where the merge field is missing entirely."""
        calls = [
            _make_tool_call(
                tool_name="internal_search",
                tool_args={},  # No queries field
            ),
            _make_tool_call(
                tool_name="internal_search",
                tool_args={"queries": ["q1"]},
            ),
        ]
        result = _merge_tool_calls(calls)

        assert len(result) == 1
        assert result[0].tool_args["queries"] == ["q1"]

    def test_handles_string_value_instead_of_list(self) -> None:
        """Handles edge case where merge field is a string instead of list."""
        calls = [
            _make_tool_call(
                tool_name="internal_search",
                tool_args={"queries": "single_query"},  # String instead of list
            ),
            _make_tool_call(
                tool_name="internal_search",
                tool_args={"queries": ["q2"]},
            ),
        ]
        result = _merge_tool_calls(calls)

        assert len(result) == 1
        # String should be converted to list item
        assert result[0].tool_args["queries"] == ["single_query", "q2"]
