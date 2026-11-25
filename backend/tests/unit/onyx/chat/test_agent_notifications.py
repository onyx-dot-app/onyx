"""A finished agent reaches the agent that started it as one agent
notification in every tool family: its answer, its error when it failed,
and the agents that it started and that still run."""

import json

from onyx.agents.models import (
    AgentCompletion,
    InputMessageMetadata,
    InputSource,
    RunFailure,
    RunFailureKind,
    RunStatus,
)
from onyx.chat.run_store import agent_result_message
from onyx.llm.models import AssistantMessage, TextContent

HEADER = [
    "<agent_notification>",
    "This is an automatic update about an agent you started, not a message "
    "from the user.",
]


def test_a_completed_agent_gives_its_answer_and_the_agents_still_running() -> None:
    message = agent_result_message(
        AgentCompletion(
            agent_path="/root/research",
            run_id="7",
            status=RunStatus.COMPLETE,
            output=AssistantMessage(content=[TextContent(text="Café [1]")]),
        ),
        ["/root/review", "/root/write"],
    )
    *header, result, footer = message.text.splitlines()
    assert header == HEADER and footer == "</agent_notification>"
    # Non-ASCII stays as written, for citation remapping.
    assert '"Café [1]"' in result
    assert json.loads(result) == {
        "agent": "/root/research",
        "status": "complete",
        "answer": "Café [1]",
        "still_running": ["/root/review", "/root/write"],
    }
    assert message.metadata == InputMessageMetadata(
        source=InputSource.AGENT_RESULT, source_run_id="7"
    )


def test_a_failed_agent_gives_its_error() -> None:
    message = agent_result_message(
        AgentCompletion(
            agent_path="/root/research",
            run_id="8",
            status=RunStatus.ERROR,
            failure=RunFailure(kind=RunFailureKind.EXECUTION, message="Worker failed"),
        ),
        [],
    )
    assert json.loads(message.text.splitlines()[2]) == {
        "agent": "/root/research",
        "status": "error",
        "answer": "",
        "error": "Worker failed",
        "still_running": [],
    }
