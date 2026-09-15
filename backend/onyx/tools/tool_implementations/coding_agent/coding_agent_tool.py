from collections.abc import Awaitable, Callable

from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing_extensions import override

from onyx.agents.tools import ToolInvocation, ToolProgress
from onyx.coding_agent.agent import BASH_TOOL_SENTINEL_ID, CodingAgent, _setup_session
from onyx.coding_agent.models import CodingAgentCallResult
from onyx.coding_agent.tool_definitions import (
    CODING_AGENT_QUERY_KEY,
    CODING_AGENT_REPO_KEY,
    CODING_AGENT_TOOL_NAME,
)
from onyx.llm.factory import get_llm_token_counter
from onyx.llm.interfaces import LLM
from onyx.llm.models import ToolResult
from onyx.prompts.coding_agent.coding_agent import MAX_CODING_AGENT_CYCLES
from onyx.tools.interface import (
    FunctionToolDefinition,
    Tool,
    ToolContext,
    parse_tool_arguments,
)
from onyx.tools.progress import CodingCompleted, CodingStarted
from onyx.tools.tool_implementations.bash.bash_tool import BashTool
from onyx.utils.logger import setup_logger

logger = setup_logger()


class CodingAgentArguments(BaseModel):
    query: str
    github_repo: str


class CodingAgentTool(Tool):
    """Top-level Tool wrapper around the coding-agent loop.

    Exposes a single LLM-facing tool that takes a query + GitHub repo,
    runs the inner agent loop (downloads repo, opens a code-interpreter
    session, drives bash commands), and returns the final text answer
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
        llm: LLM,
        github_token: str | None = None,
    ) -> None:
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
    def tool_definition(self) -> FunctionToolDefinition:
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

    @property
    def execute_async(
        self,
    ) -> Callable[[ToolInvocation, ToolContext], Awaitable[ToolResult]]:
        return self._execute

    async def _execute(
        self, invocation: ToolInvocation, _context: ToolContext
    ) -> ToolResult:
        arguments = parse_tool_arguments(CodingAgentArguments, invocation.arguments)
        invocation.update(
            ToolProgress(
                details=CodingStarted(query=arguments.query, repo=arguments.github_repo)
            )
        )
        sandbox = _setup_session(
            repo=arguments.github_repo, github_token=self._github_token
        )
        session_id = await invocation.run_blocking(sandbox.__enter__)
        try:
            feature = CodingAgent(
                query=arguments.query,
                repo=arguments.github_repo,
                llm=self._llm,
                token_counter=get_llm_token_counter(self._llm),
                user_identity=None,
                bash_tool=BashTool(
                    tool_id=BASH_TOOL_SENTINEL_ID, session_id=session_id
                ),
            )
            completed = await invocation.run_child(
                feature.agent,
                max_steps=MAX_CODING_AGENT_CYCLES + 1,
                messages=feature.input_messages,
            )
            answer = completed.output.text
            if not answer:
                raise ValueError("Coding agent produced no final answer")
            invocation.update(ToolProgress(details=CodingCompleted(answer=answer)))
            return ToolResult(
                content=answer, details=CodingAgentCallResult(answer=answer)
            )
        finally:
            try:
                await invocation.run_blocking(
                    lambda: sandbox.__exit__(None, None, None), cleanup=True
                )
            except Exception:
                logger.exception("Coding sandbox cleanup failed")
