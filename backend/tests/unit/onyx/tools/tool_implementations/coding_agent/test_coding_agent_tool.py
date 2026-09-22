"""Unit tests for CodingAgentTool.

Coverage is intentionally narrow — the heavy lifting lives in
``run_coding_agent_call`` and ``BashTool``, both tested separately. This
file exists to lock in the wiring this Tool wrapper is responsible for.
"""

from unittest.mock import MagicMock, patch

from onyx.tools.tool_implementations.coding_agent.coding_agent_tool import (
    CodingAgentTool,
)


def test_is_available_delegates_to_bash_tool() -> None:
    """CodingAgentTool can't function without BashTool, so its availability
    must be a strict subset. Delegation keeps the env / DB / health /
    version-gate checks in one place instead of drifting between two
    implementations."""
    db_session = MagicMock()

    with patch(
        "onyx.tools.tool_implementations.coding_agent.coding_agent_tool"
        ".BashTool.is_available",
        return_value=True,
    ) as mock_is_available:
        assert CodingAgentTool.is_available(db_session) is True
        mock_is_available.assert_called_once_with(db_session)


def test_is_available_false_when_bash_tool_unavailable() -> None:
    db_session = MagicMock()

    with patch(
        "onyx.tools.tool_implementations.coding_agent.coding_agent_tool"
        ".BashTool.is_available",
        return_value=False,
    ):
        assert CodingAgentTool.is_available(db_session) is False


def test_async_delegation_keeps_parent_context_and_call_identity() -> None:
    import asyncio
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from pydantic_ai import RunContext

    from onyx.server.query_and_chat.placement import Placement
    from onyx.tools.tool_implementations.coding_agent.coding_agent_tool import (
        CodingAgentToolOverrideKwargs,
    )

    async def run() -> None:
        context = MagicMock(spec=RunContext)
        context.tool_call_id = "native-coding-call"
        emitter = MagicMock()
        tool = CodingAgentTool(tool_id=12, emitter=emitter, llm=MagicMock())
        delegate = AsyncMock(return_value=SimpleNamespace(answer="Repository answer"))
        with (
            patch("onyx.tools.subagents.coding_agent.run_coding_agent_call", delegate),
            patch(
                "onyx.tools.tool_implementations.coding_agent.coding_agent_tool.get_llm_token_counter",
                return_value=len,
            ),
        ):
            response = await tool.run_async(
                context,
                placement=Placement(turn_index=2),
                override_kwargs=CodingAgentToolOverrideKwargs(),
                query="Explain startup",
                github_repo="onyx-dot-app/onyx",
            )
        assert response.llm_facing_response == "Repository answer"
        assert delegate.await_args is not None
        kwargs = delegate.await_args.kwargs
        assert kwargs["parent_context"] is context
        assert kwargs["coding_agent_call"].tool_call_id == "native-coding-call"
        assert kwargs["coding_agent_call"].tool_args == {
            "query": "Explain startup",
            "github_repo": "onyx-dot-app/onyx",
        }
        emitter.report.assert_called_once()

    asyncio.run(run())
