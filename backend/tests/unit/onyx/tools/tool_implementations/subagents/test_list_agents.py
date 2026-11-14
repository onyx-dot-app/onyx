from unittest.mock import MagicMock

import pytest

from onyx.agents.models import AgentInfo, RunStatus
from onyx.agents.tools import ToolInvocation
from onyx.tools.tool_implementations.subagents.subagent_tools import ListAgentsTool

# Agents of earlier user turns are listed while unfinished.
_AGENTS = [
    AgentInfo(
        id="root",
        path="/root",
        parent_id=None,
        description="",
        restoration_config=None,
        latest_run_id="10",
        status=RunStatus.COMPLETE,
        current_turn=True,
    ),
    *(
        AgentInfo(
            id=name,
            path=f"/root/{name}",
            parent_id="root",
            description="",
            restoration_config=None,
            latest_run_id=run_id,
            status=status,
            current_turn=current_turn,
        )
        for name, run_id, status, current_turn in [
            ("earlier", "4", RunStatus.COMPLETE, False),
            ("suspended", "5", RunStatus.SUSPENDED, False),
            ("running", "12", RunStatus.RUNNING, True),
            # Started in this turn before the root waited; read by a follow-up.
            ("finished", "13", RunStatus.ERROR, True),
        ]
    ),
]


@pytest.mark.parametrize(
    ("arguments", "listed", "hidden"),
    [
        ({}, ["/root", "/root/finished", "/root/running", "/root/suspended"], 1),
        (
            {"include_finished": True},
            [
                "/root",
                "/root/earlier",
                "/root/finished",
                "/root/running",
                "/root/suspended",
            ],
            0,
        ),
        ({"path_prefix": "/root/e"}, [], 1),
    ],
    ids=["this_turn", "include_finished", "prefix"],
)
def test_list_agents_hides_agents_that_finished_before_this_turn(
    arguments: dict[str, str | bool], listed: list[str], hidden: int
) -> None:
    invocation = MagicMock(spec=ToolInvocation)
    invocation.arguments = arguments
    invocation.agents.discover_agents.return_value = _AGENTS
    invocation.agents.agent_id = "root"

    lines = ListAgentsTool()._run(invocation, MagicMock()).text.splitlines()

    assert [line.split(" ", 1)[0] for line in lines if line.startswith("/")] == listed
    assert any(line.startswith("Not shown") for line in lines) is bool(hidden)
    if hidden:
        assert lines[-1].startswith(f"Not shown: {hidden} finished agents")
