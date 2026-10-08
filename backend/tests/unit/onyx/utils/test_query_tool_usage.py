"""Query categories reflect executed tools, including failures and parallel calls."""

from unittest.mock import Mock

import pytest

from onyx.agents.tools import ToolInvocation
from onyx.llm.cancellation import CancellationSignal
from onyx.llm.models import ToolResult
from onyx.tools.interface import Tool, ToolContext
from onyx.tools.tool_implementations.search.search_tool import SearchTool
from onyx.tools.tool_implementations.web_search.web_search_tool import WebSearchTool
from onyx.utils import fleet_query_telemetry as telemetry
from onyx.utils.fleet_telemetry import sanitize_data
from onyx.utils.threadpool_concurrency import run_functions_tuples_in_parallel


@pytest.mark.parametrize(
    "tool_types,expected",
    [
        ([], "none"),
        ([SearchTool, SearchTool], "search_only"),
        ([WebSearchTool], "other_only"),
        ([Tool], "other_only"),
        ([SearchTool, Tool, SearchTool], "search_and_other"),
    ],
)
@pytest.mark.parametrize("fails", [False, True])
def test_executed_tools_determine_one_query_category(
    monkeypatch: pytest.MonkeyPatch,
    tool_types: list[type[Tool]],
    expected: str,
    fails: bool,
) -> None:
    sink = Mock()
    monkeypatch.setattr(telemetry, "emit_telemetry", sink)
    observation = telemetry.QueryObservation(channel="web", mode="chat")
    for tool_type in tool_types:
        tool = Mock(spec=tool_type)
        # A custom tool with a search-like name must still count as another tool.
        tool.name = SearchTool.NAME
        tool._run.return_value = ToolResult(content="private result")
        if fails:
            tool._run.side_effect = RuntimeError("private error")
        call = ToolInvocation(
            call_id="call-1",
            arguments={"query": "private query"},
            cancellation=CancellationSignal(),
            update=lambda _: None,
        )
        token = telemetry.CURRENT_QUERY_OBSERVATION.set(observation)
        try:
            Tool.run(tool, call, ToolContext())
        finally:
            telemetry.CURRENT_QUERY_OBSERVATION.reset(token)
        tool._run.assert_called_once()
    observation.finish()
    observation.finish()
    sink.assert_called_once()
    event_type, data = sink.call_args.args
    assert event_type == "query"
    assert data["tool_usage"] == expected
    assert sanitize_data(event_type, data) is not None
    assert "private" not in str(data)


def test_parallel_models_share_usage_and_cancellation_freezes_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sink = Mock()
    monkeypatch.setattr(telemetry, "emit_telemetry", sink)
    observation = telemetry.QueryObservation(channel="api", mode="chat")
    run_functions_tuples_in_parallel(
        [
            (lambda: observation.tool_started(is_search=True), ()),
            (lambda: observation.tool_started(is_search=False), ()),
        ]
    )
    observation.outcome = "canceled"
    observation.finish()
    assert sink.call_args.args[1]["tool_usage"] == "search_and_other"
    assert sink.call_args.args[1]["outcome"] == "canceled"

    stopped = telemetry.QueryObservation(channel="web", mode="chat")
    stopped.tool_started(is_search=True)
    stopped.finish()
    stopped.tool_started(is_search=False)
    stopped.finish()
    assert sink.call_count == 2
    assert sink.call_args.args[1]["tool_usage"] == "search_only"


def test_search_mode_does_not_claim_chat_tool_usage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sink = Mock()
    monkeypatch.setattr(telemetry, "emit_telemetry", sink)
    telemetry.QueryObservation(channel="api", mode="search").finish()
    assert sink.call_args.args[1]["tool_usage"] is None
