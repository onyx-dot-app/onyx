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
    CODING_AGENT_REF_KEY,
    CODING_AGENT_REPO_KEY,
)
from onyx.db.credentials import ConnectorRepoAccess
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
def _run_mocks(
    access: ConnectorRepoAccess | None, seed_paths: list[str]
) -> Iterator[MagicMock]:
    inner = MagicMock(return_value=MagicMock(answer="done"))
    with (
        patch(f"{_TOOL_MODULE}.get_session_with_current_tenant"),
        patch(f"{_TOOL_MODULE}.get_llm_token_counter", return_value=len),
        patch.object(CodingAgentTool, "_fetch_connector_access", return_value=access),
        patch.object(CodingAgentTool, "_fetch_seed_paths", return_value=seed_paths),
        patch(
            "onyx.tools.fake_tools.coding_agent.run_coding_agent_call",
            new=inner,
        ),
    ):
        yield inner


def _run(tool: CodingAgentTool, ref: str | None = None) -> None:
    tool.run(
        placement=Placement(turn_index=0, tab_index=0),
        override_kwargs=CodingAgentToolOverrideKwargs(),
        **{
            CODING_AGENT_QUERY_KEY: "where is auth handled",
            CODING_AGENT_REPO_KEY: "onyx-dot-app/onyx",
            **({CODING_AGENT_REF_KEY: ref} if ref else {}),
        },
    )


def test_seeds_even_without_a_connector_credential() -> None:
    """Seed paths come from the user's own ACL-filtered index read, so they
    do not depend on any credential being lendable."""
    with _run_mocks(access=None, seed_paths=["a.py"]) as inner:
        _run(_tool())

    assert inner.call_args.kwargs["seed_paths"] == ["a.py"]
    assert inner.call_args.kwargs["github_token"] is None


def test_lends_the_credential_only_when_the_gate_returns_one() -> None:
    access = ConnectorRepoAccess(token="tok", branch=None)
    with _run_mocks(access=access, seed_paths=[]) as inner:
        _run(_tool())

    assert inner.call_args.kwargs["github_token"] == "tok"


def test_a_lent_credential_pins_the_ref_to_the_indexed_branch() -> None:
    """The connector indexes one branch; an old branch can still hold what
    was deliberately removed from it, so the model does not pick the ref."""
    access = ConnectorRepoAccess(token="tok", branch="main")
    with _run_mocks(access=access, seed_paths=[]) as inner:
        _run(_tool(), ref="secrets-experiment")

    call = inner.call_args.kwargs["coding_agent_call"]
    assert call.tool_args[CODING_AGENT_REF_KEY] == "main"


def test_a_public_repo_still_honours_the_requested_ref() -> None:
    with _run_mocks(access=None, seed_paths=[]) as inner:
        _run(_tool(), ref="v1.2.3")

    call = inner.call_args.kwargs["coding_agent_call"]
    assert call.tool_args[CODING_AGENT_REF_KEY] == "v1.2.3"


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
