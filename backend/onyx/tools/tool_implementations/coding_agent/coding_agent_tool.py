import asyncio
from typing import Any, cast

from pydantic import BaseModel
from pydantic_ai import RunContext
from sqlalchemy.orm import Session
from typing_extensions import override

from onyx.chat.emitter import Emitter
from onyx.coding_agent.mock_tools import (
    CODING_AGENT_QUERY_KEY,
    CODING_AGENT_REPO_KEY,
    CODING_AGENT_TOOL_NAME,
)
from onyx.llm.factory import get_llm_token_counter
from onyx.llm.interfaces import LLM
from onyx.server.query_and_chat.placement import Placement
from onyx.server.query_and_chat.streaming_models import CodingAgentStart
from onyx.tools.interface import Tool
from onyx.tools.models import ToolCallException, ToolCallKickoff, ToolResponse
from onyx.tools.tool_implementations.bash.bash_tool import BashTool
from onyx.utils.logger import setup_logger

logger = setup_logger()


class CodingAgentToolOverrideKwargs(BaseModel):
    pass


class CodingAgentTool(Tool[CodingAgentToolOverrideKwargs]):
    """Domain tool for native coding-agent delegation.

    Exposes a single LLM-facing tool that takes a query + GitHub repo,
    delegates repository work to a child agent with a code-interpreter
    session and returns its final text answer
    as the tool response.
    """

    NAME = CODING_AGENT_TOOL_NAME
    DISPLAY_NAME = "Coding Agent"
    DESCRIPTION = (
        "Investigate and answer a coding question against a specific GitHub "
        "repository. Clones the repo into an isolated sandbox and explores "
        "it via shell commands before returning a text answer."
    )

    def __init__(
        self,
        tool_id: int,
        emitter: Emitter,
        llm: LLM,
        github_token: str | None = None,
    ) -> None:
        super().__init__(emitter=emitter)
        self._id = tool_id
        self._llm = llm
        self._github_token = github_token

    @property
    def id(self) -> int:
        return self._id

    @property
    def name(self) -> str:
        return self.NAME

    @property
    def description(self) -> str:
        return self.DESCRIPTION

    @property
    def display_name(self) -> str:
        return self.DISPLAY_NAME

    @override
    @classmethod
    def is_available(cls, db_session: Session) -> bool:
        """Available iff ``BashTool`` is available."""
        return BashTool.is_available(db_session)

    @override
    def tool_definition(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        CODING_AGENT_QUERY_KEY: {
                            "type": "string",
                            "description": (
                                "The user's question or task to perform "
                                "against the repository."
                            ),
                        },
                        CODING_AGENT_REPO_KEY: {
                            "type": "string",
                            "description": (
                                "GitHub repository URL or 'owner/repo' "
                                "identifier (e.g. "
                                "'https://github.com/onyx-dot-app/onyx' "
                                "or 'onyx-dot-app/onyx')."
                            ),
                        },
                    },
                    "required": [CODING_AGENT_QUERY_KEY, CODING_AGENT_REPO_KEY],
                },
            },
        }

    @override
    def emit_start(self, placement: Placement) -> None:
        # query and repo aren't bound until run(); CodingAgentStart is emitted
        # there, mirroring PythonTool's pattern.
        return

    @override
    def run(
        self,
        placement: Placement,
        override_kwargs: CodingAgentToolOverrideKwargs,
        **llm_kwargs: Any,
    ) -> ToolResponse:
        raise RuntimeError("Coding agents require native async delegation.")

    async def run_async(
        self,
        parent_context: RunContext[None],
        placement: Placement,
        override_kwargs: CodingAgentToolOverrideKwargs,
        **llm_kwargs: Any,
    ) -> ToolResponse:
        del override_kwargs
        if CODING_AGENT_QUERY_KEY not in llm_kwargs:
            raise ToolCallException(
                message=f"Missing '{CODING_AGENT_QUERY_KEY}' in coding_agent call",
                llm_facing_message=(
                    f"The {self.name} tool requires a "
                    f"'{CODING_AGENT_QUERY_KEY}' parameter."
                ),
            )
        if CODING_AGENT_REPO_KEY not in llm_kwargs:
            raise ToolCallException(
                message=f"Missing '{CODING_AGENT_REPO_KEY}' in coding_agent call",
                llm_facing_message=(
                    f"The {self.name} tool requires a "
                    f"'{CODING_AGENT_REPO_KEY}' parameter."
                ),
            )
        query = cast(str, llm_kwargs[CODING_AGENT_QUERY_KEY])
        repo = cast(str, llm_kwargs[CODING_AGENT_REPO_KEY])

        await asyncio.to_thread(
            self.emitter.report,
            placement=placement,
            obj=CodingAgentStart(query=query, repo=repo),
        )

        # Imported lazily to avoid a circular import: coding_agent.py imports
        # the BashTool which lives in tool_implementations alongside us.
        from onyx.tools.subagents.coding_agent import run_coding_agent_call

        if parent_context.tool_call_id is None:
            raise ValueError(
                "Coding delegation requires a native tool call identifier."
            )
        coding_call = ToolCallKickoff(
            tool_call_id=parent_context.tool_call_id,
            tool_name=self.name,
            tool_args={
                CODING_AGENT_QUERY_KEY: query,
                CODING_AGENT_REPO_KEY: repo,
            },
            placement=placement,
        )

        token_counter = get_llm_token_counter(self._llm)

        result = await run_coding_agent_call(
            parent_context=parent_context,
            coding_agent_call=coding_call,
            emitter=self.emitter,
            llm=self._llm,
            token_counter=token_counter,
            user_identity=None,
            github_token=self._github_token,
        )

        if result is None:
            failure_msg = (
                "Coding agent failed to produce an answer. "
                "Check the server logs for the underlying error."
            )
            logger.warning("Coding agent run returned None for query: %s", query)
            return ToolResponse(
                rich_response=None,
                llm_facing_response=failure_msg,
            )

        return ToolResponse(
            rich_response=result.answer,
            llm_facing_response=result.answer,
        )
