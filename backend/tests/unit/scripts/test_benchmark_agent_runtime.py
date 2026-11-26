"""The agent runtime benchmark measures only complete chats with bounded
search results."""

import pytest
from scripts.benchmark_agent_runtime import (
    DOCUMENTS_PER_SEARCH,
    MIN_RESULT_CHARS,
    BenchSearchTool,
    run_chat,
)

from onyx.agents.tools import ToolInvocation
from onyx.llm.cancellation import CancellationSignal
from onyx.tools.constants import DEFAULT_MAX_OUTPUT_CHARS
from onyx.tools.models import ToolContext


@pytest.mark.parametrize("result_chars", [MIN_RESULT_CHARS, DEFAULT_MAX_OUTPUT_CHARS])
def test_search_result_fits_the_requested_size(result_chars: int) -> None:
    result = BenchSearchTool(0.0, result_chars)._run(
        ToolInvocation(
            call_id="call",
            arguments={},
            cancellation=CancellationSignal(),
            update=lambda _progress: None,
        ),
        ToolContext(),
    )
    assert result_chars - DOCUMENTS_PER_SEARCH < len(result.content) <= result_chars


def test_chat_whose_searches_fail_is_not_measured() -> None:
    # A negative sleep makes every search raise; the tool reports an error
    # result and the scripted model still answers.
    with pytest.raises(RuntimeError, match="ran 0 of 2 searches"):
        run_chat(0, 3, MIN_RESULT_CHARS, 0.0, -1.0)
