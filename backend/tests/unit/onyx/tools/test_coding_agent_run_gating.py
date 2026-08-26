"""The coding agent gates two capabilities that used to share one predicate.

Reading the index for seed paths is an ordinary, ACL-checked read. Borrowing
the connector's GitHub credential hands the sandbox the full source tree.
These tests pin them apart.
"""

from contextlib import contextmanager
from typing import Any, Iterator
from unittest.mock import MagicMock, patch

import pytest

from onyx.coding_agent.mock_tools import (
    CODING_AGENT_QUERY_KEY,
    CODING_AGENT_REPO_KEY,
)
from onyx.server.query_and_chat.placement import Placement
from onyx.tools.models import ToolCallException
from onyx.tools.tool_implementations.coding_agent.coding_agent_tool import (
    CodingAgentTool,
    CodingAgentToolOverrideKwargs,
)

_TOOL_MODULE = "onyx.tools.tool_implementations.coding_agent.coding_agent_tool"


def _tool(user: Any = None) -> CodingAgentTool:
    return CodingAgentTool(
        tool_id=1,
        emitter=MagicMock(),
        llm=MagicMock(),
        user=user if user is not None else MagicMock(),
    )


@contextmanager
def _run_mocks(token: str | None, seed_paths: list[str]) -> Iterator[MagicMock]:
    inner = MagicMock(return_value=MagicMock(answer="done"))
    with (
        patch(f"{_TOOL_MODULE}.get_session_with_current_tenant"),
        patch(f"{_TOOL_MODULE}.get_llm_token_counter", return_value=len),
        patch.object(CodingAgentTool, "_fetch_connector_token", return_value=token),
        patch.object(CodingAgentTool, "_fetch_seed_paths", return_value=seed_paths),
        patch(
            "onyx.tools.fake_tools.coding_agent.run_coding_agent_call",
            new=inner,
        ),
    ):
        yield inner


def _run(tool: CodingAgentTool) -> None:
    tool.run(
        placement=Placement(turn_index=0, tab_index=0),
        override_kwargs=CodingAgentToolOverrideKwargs(),
        **{
            CODING_AGENT_QUERY_KEY: "where is auth handled",
            CODING_AGENT_REPO_KEY: "onyx-dot-app/onyx",
        },
    )


def test_seeds_even_without_a_connector_credential() -> None:
    """Seed paths come from the user's own ACL-filtered index read, so they
    do not depend on any credential being lendable."""
    with _run_mocks(token=None, seed_paths=["a.py"]) as inner:
        _run(_tool())

    assert inner.call_args.kwargs["seed_paths"] == ["a.py"]
    assert inner.call_args.kwargs["github_token"] is None


def test_lends_the_credential_only_when_the_gate_returns_one() -> None:
    with _run_mocks(token="tok", seed_paths=[]) as inner:
        _run(_tool())

    assert inner.call_args.kwargs["github_token"] == "tok"


def test_rejects_unparseable_repo() -> None:
    tool = _tool()
    with pytest.raises(ToolCallException):
        tool.run(
            placement=Placement(turn_index=0, tab_index=0),
            override_kwargs=CodingAgentToolOverrideKwargs(),
            **{
                CODING_AGENT_QUERY_KEY: "q",
                CODING_AGENT_REPO_KEY: "not a repo at all",
            },
        )
