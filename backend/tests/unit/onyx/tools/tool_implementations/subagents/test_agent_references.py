import pytest

from onyx.agents.models import AgentInfo
from onyx.tools.models import ToolCallException
from onyx.tools.tool_implementations.subagents.subagent_tools import _find_agent


def _agent(agent_id: str, path: str, parent_id: str | None) -> AgentInfo:
    return AgentInfo(
        id=agent_id,
        path=path,
        parent_id=parent_id,
        description="",
        restoration_config=None,
    )


_AGENTS = [
    _agent("root-id", "/root", None),
    _agent("writer-id", "/root/writer", "root-id"),
    _agent("research-id", "/root/research", "root-id"),
]


@pytest.mark.parametrize(
    ("caller_id", "target", "found_id"),
    [
        ("writer-id", "..", "root-id"),
        # Older chats show agent IDs in their history.
        ("root-id", "research-id", "research-id"),
    ],
)
def test_find_agent_resolves_the_parent_and_agent_ids(
    caller_id: str, target: str, found_id: str
) -> None:
    assert _find_agent(_AGENTS, caller_id, target).id == found_id


def test_a_repeated_path_in_an_older_chat_names_the_newest_agent() -> None:
    """The directory lists agents from the newest spawning response first."""
    newer = _agent("newer-id", "/root/research", "root-id")

    found = _find_agent([_AGENTS[0], newer, _AGENTS[2]], "root-id", "/root/research")

    assert found.id == "newer-id"


@pytest.mark.parametrize(
    ("caller_id", "target", "error"),
    [
        (
            "root-id",
            "..",
            "You are the root agent, so you have no parent. Use list_agents to "
            "find agents.",
        ),
        (
            "root-id",
            "/root/missing",
            "No agent on this chat branch has the path '/root/missing'. Use a "
            "path that list_agents shows.",
        ),
    ],
)
def test_find_agent_refuses_targets_without_an_agent(
    caller_id: str, target: str, error: str
) -> None:
    with pytest.raises(ToolCallException) as raised:
        _find_agent(_AGENTS, caller_id, target)

    assert raised.value.llm_facing_message == error
