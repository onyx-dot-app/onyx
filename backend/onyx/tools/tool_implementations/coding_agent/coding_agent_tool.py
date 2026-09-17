from concurrent.futures import Future

from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing_extensions import override

from onyx.agents.concurrency import CLEANUP_SECONDS
from onyx.agents.tools import ToolInvocation
from onyx.agents.transcript import AgentRestorationConfig
from onyx.coding_agent.agent import BASH_TOOL_SENTINEL_ID, CodingAgent, _setup_session
from onyx.coding_agent.models import CodingAgentCallResult
from onyx.coding_agent.tool_definitions import (
    CODING_AGENT_QUERY_KEY,
    CODING_AGENT_REPO_KEY,
    CODING_AGENT_TOOL_NAME,
)
from onyx.llm.cancellation import CancellationSignal, cancellation_scope
from onyx.llm.factory import get_llm_token_counter
from onyx.llm.interfaces import LLM
from onyx.llm.models import ToolResult, UserMessage
from onyx.prompts.coding_agent.coding_agent import MAX_CODING_AGENT_CYCLES
from onyx.tools.interface import (
    FunctionToolDefinition,
    Tool,
    ToolContext,
    parse_tool_arguments,
)
from onyx.tools.tool_implementations.bash.bash_tool import BashTool
from onyx.utils.logger import setup_logger
from onyx.utils.threadpool_concurrency import start_thread_with_context

logger = setup_logger()


class CodingAgentArguments(BaseModel):
    query: str
    github_repo: str


class CodingAgentTool(Tool):
    """Investigate a repository in a sandbox owned by one tool invocation."""

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

    @override
    def run(self, invocation: ToolInvocation, context: ToolContext) -> ToolResult:  # noqa: ARG002
        arguments = parse_tool_arguments(CodingAgentArguments, invocation.arguments)
        sandbox = _setup_session(
            repo=arguments.github_repo, github_token=self._github_token
        )
        session_id = sandbox.__enter__()
        feature: CodingAgent | None = None
        child_run_id: str | None = None
        try:
            feature = CodingAgent(
                repo=arguments.github_repo,
                llm=self._llm,
                token_counter=get_llm_token_counter(self._llm),
                user_identity=None,
                bash_tool=BashTool(
                    tool_id=BASH_TOOL_SENTINEL_ID, session_id=session_id
                ),
            )
            submission = invocation.agents.spawn_agent(
                feature.agent,
                name="coding-"
                + "".join(
                    char if char.isascii() and char.isalnum() else "-"
                    for char in invocation.call_id.lower()
                ),
                description=arguments.query,
                max_steps=MAX_CODING_AGENT_CYCLES + 1,
                messages=[UserMessage(content=arguments.query)],
                restoration_config=AgentRestorationConfig(
                    feature="coding", settings={"repo": arguments.github_repo}
                ),
            )
            child_run_id = submission.run_id
            while (completed := invocation.agents.wait_run(submission.run_id)) is None:
                invocation.cancellation.check()
            answer = completed.output.text
            if not answer:
                raise ValueError("Coding agent produced no final answer")
            return ToolResult(
                content=answer, details=CodingAgentCallResult(answer=answer)
            )
        finally:
            if feature is not None:
                feature.is_sandbox_available = False

            def cleanup() -> None:
                try:
                    with cancellation_scope(CancellationSignal()):
                        sandbox.__exit__(None, None, None)
                except Exception:
                    logger.exception("Coding sandbox cleanup failed")

            if child_run_id is None or invocation.agents.wait_for_idle(
                child_run_id, timeout=CLEANUP_SECONDS
            ):
                cleanup()
            else:
                # Retain the sandbox and cleanup ownership until child work drains.
                logger.warning("Deferring coding sandbox cleanup: %s", child_run_id)
                completion: Future[None] = Future()
                completion.set_running_or_notify_cancel()
                invocation.cancellation.track_operation(completion)

                def finish_cleanup() -> None:
                    try:
                        cleanup()
                    finally:
                        completion.set_result(None)

                def start_cleanup() -> None:
                    try:
                        start_thread_with_context(
                            finish_cleanup, name="coding-sandbox-cleanup", daemon=True
                        )
                    except RuntimeError:
                        logger.exception(
                            "Could not start coding sandbox cleanup thread"
                        )
                        finish_cleanup()

                invocation.agents.add_idle_callback(child_run_id, start_cleanup)
