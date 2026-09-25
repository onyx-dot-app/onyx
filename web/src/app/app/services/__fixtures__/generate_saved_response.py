"""Generate savedResponse.json with the backend history projector.

From the repository root:
PYTHONPATH=backend uv run python web/src/app/app/services/__fixtures__/generate_saved_response.py
"""

import json
from pathlib import Path

from onyx.agents.execution_records import ExecutionStatus, RunStatus
from onyx.agents.models import StepRecord, ToolExecutionRecord
from onyx.chat.models import ResponseRecord
from onyx.llm.models import (
    AssistantMessage,
    Message,
    TextContent,
    ThinkingContent,
    ToolCall,
    ToolResultMessage,
)
from onyx.server.query_and_chat.session_loading import _response_packets


def record(
    run: str,
    messages: list[Message],
    *,
    parent_run_id: str | None = None,
    parent_message_id: str | None = None,
    parent_tool_call_id: str | None = None,
) -> ResponseRecord:
    steps: list[StepRecord] = []
    for message in messages:
        if isinstance(message, AssistantMessage):
            steps.append(
                StepRecord(message=message, generation_status=ExecutionStatus.COMPLETE)
            )
        elif isinstance(message, ToolResultMessage):
            steps[-1].tools[message.tool_call_id] = ToolExecutionRecord(
                status=ExecutionStatus.COMPLETE,
                result=message,
            )
        else:
            raise ValueError("Response output must contain assistant or tool messages")
    return ResponseRecord(
        run_id=run,
        steps=steps,
        answer_step_index=len(steps) - 1,
        status=RunStatus.COMPLETE,
        parent_run_id=parent_run_id,
        parent_message_id=parent_message_id,
        parent_tool_call_id=parent_tool_call_id,
    )


root = record(
    "root",
    [
        AssistantMessage(
            id="root:0",
            content=[
                ThinkingContent(text="Consider sources"),
                TextContent(text="Checking both sources."),
                ToolCall(id="a", name="research_agent", arguments={"query": "first"}),
                ToolCall(id="b", name="research_agent", arguments={"query": "second"}),
            ],
        ),
        ToolResultMessage(
            tool_call_id="a", tool_name="research_agent", content="First source"
        ),
        ToolResultMessage(
            tool_call_id="b", tool_name="research_agent", content="Second source"
        ),
        AssistantMessage(
            id="root:1",
            content=[
                ToolCall(
                    id="a", name="open_url", arguments={"url": "https://example.com"}
                )
            ],
        ),
        ToolResultMessage(tool_call_id="a", tool_name="open_url", content="Verified"),
        AssistantMessage(id="root:2", content=[TextContent(text="The final answer.")]),
    ],
)
for call in ["a", "b"]:
    root.child_runs.append(
        record(
            f"child-{call}",
            [
                AssistantMessage(
                    id=f"child-{call}:0", content=[TextContent(text=f"Source {call}")]
                )
            ],
            parent_run_id="root",
            parent_message_id="root:0",
            parent_tool_call_id=call,
        )
    )
packets = _response_packets(root, 12, {}, {}, {}, {})
Path(__file__).with_name("savedResponse.json").write_text(
    json.dumps([p.model_dump(mode="json") for p in packets], indent=2) + "\n"
)
