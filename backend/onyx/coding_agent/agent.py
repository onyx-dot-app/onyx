from collections.abc import Callable, Iterator
from contextlib import contextmanager

from onyx.agents.runtime import Agent, AgentContext, AgentHooks, AgentStep, StepResult
from onyx.agents.tools import AgentTool, ToolExecutionMode, ToolInvocation
from onyx.coding_agent.tool_definitions import (
    BASH_TOOL_DESCRIPTION,
    CODING_AGENT_THINK_TOOL_DESCRIPTION,
    GENERATE_ANSWER_TOOL_DESCRIPTION,
    GENERATE_ANSWER_TOOL_NAME,
)
from onyx.context.messages import PromptMetadata, prepare_model_messages
from onyx.context.prompt import prepare_prompt
from onyx.deep_research.tool_definitions import THINK_TOOL_RESPONSE_MESSAGE
from onyx.llm.cancellation import check_cancelled
from onyx.llm.interfaces import LLM, GenerationContext, LLMUserIdentity
from onyx.llm.model_capabilities import model_is_reasoning_model
from onyx.llm.models import (
    GenerationRequest,
    Message,
    ReasoningEffort,
    SystemMessage,
    ToolChoiceOptions,
    ToolResult,
    UserMessage,
)
from onyx.prompts.coding_agent.coding_agent import (
    CODING_AGENT_FINAL_ANSWER_PROMPT,
    CODING_AGENT_PROMPT,
    CODING_AGENT_PROMPT_REASONING,
    USER_FINAL_ANSWER_QUERY,
)
from onyx.prompts.prompt_utils import get_current_llm_day_time
from onyx.tools.interface import FunctionToolDefinition, ToolContext
from onyx.tools.tool_implementations.bash.bash_tool import BashTool
from onyx.tools.tool_implementations.python.code_interpreter_client import (
    CodeInterpreterClient,
)
from onyx.tools.tool_runner import run_tool
from onyx.tracing.flows import LLMFlow
from onyx.utils.github import download_github_archive, parse_github_source
from onyx.utils.logger import setup_logger

logger = setup_logger()

# Sandbox session lifetime; this does not limit agent execution time.
CODING_AGENT_SESSION_TTL_SECONDS = 60 * 60
# Match the code-interpreter service setup timeout.
CODING_AGENT_SETUP_TIMEOUT_MS = 60 * 1000
# Tarball is staged at this path inside the session workspace
REPO_TARBALL_PATH = "repo.tar.gz"
# Sentinel tool_id used when constructing the in-memory BashTool. Bash sub-tool
# calls are not persisted to the DB through this loop, so the id is unused.
BASH_TOOL_SENTINEL_ID = 0
MAX_FINAL_ANSWER_TOKENS = 4000
MAX_INVESTIGATION_TOKENS = 2048
CODING_AGENT_GITHUB_MAX_REPO_BYTES = 500 * 1024 * 1024
CODING_AGENT_GITHUB_DOWNLOAD_TIMEOUT = (30, 300)


@contextmanager
def _setup_session(
    repo: str,
    github_token: str | None,
) -> Iterator[str]:
    """Own a sandbox with the repository extracted at its working directory."""
    github_source = parse_github_source(
        repo,
        allow_ssh=True,
    )
    repo_bytes = download_github_archive(
        github_source,
        "HEAD",
        f"Bearer {github_token}" if github_token else None,
        max_size_bytes=CODING_AGENT_GITHUB_MAX_REPO_BYTES,
        timeout=CODING_AGENT_GITHUB_DOWNLOAD_TIMEOUT,
    )

    with CodeInterpreterClient() as client:
        ci_file_id = client.upload_file(repo_bytes, REPO_TARBALL_PATH)
        session_info = client.create_session(
            ttl_seconds=CODING_AGENT_SESSION_TTL_SECONDS,
            files=[{"path": REPO_TARBALL_PATH, "file_id": ci_file_id}],
        )
        session_id = session_info.session_id
        logger.info("Created coding agent session %s", session_id)

        try:
            # GitHub tarballs always have exactly one top-level dir;
            # --strip-components=1 extracts the contents directly into cwd so the
            # agent's bash calls see the repo root immediately.
            extract_cmd = (
                f"tar -xzf {REPO_TARBALL_PATH} --strip-components=1 "
                f"&& rm {REPO_TARBALL_PATH} && ls"
            )
            extract_result = client.execute_bash_in_session(
                session_id=session_id,
                cmd=extract_cmd,
                timeout_ms=CODING_AGENT_SETUP_TIMEOUT_MS,
            )
            if extract_result.exit_code != 0:
                raise RuntimeError(
                    f"Failed to extract repository tarball: {extract_result.stderr}"
                )
            logger.info("Extracted repo into session %s", session_id)
            check_cancelled()
            yield session_id
        finally:
            try:
                client.delete_session(session_id)
                logger.info("Deleted coding agent session %s", session_id)
            except Exception:
                # The remote TTL bounds resources when cleanup fails.
                logger.warning(
                    "Failed to delete coding agent session %s",
                    session_id,
                    exc_info=True,
                )


class CodingAgent:
    """Repository investigation and final-answer policy."""

    def __init__(
        self,
        *,
        query: str,
        repo: str,
        llm: LLM,
        token_counter: Callable[[str], int],
        user_identity: LLMUserIdentity | None,
        bash_tool: BashTool,
    ) -> None:
        self.query = query
        self.repo = repo
        self.llm = llm
        self.token_counter = token_counter
        self.bash_tool = bash_tool
        self.is_reasoning_model = model_is_reasoning_model(
            llm.info.model_name, llm.info.model_provider
        )
        self.requested_final = False
        self.is_final_step = False
        self._system_prompt = ""
        self.agent = Agent(
            llm,
            context=AgentContext(
                execution=GenerationContext(
                    flow=LLMFlow.CODING_AGENT, user_identity=user_identity
                ),
            ),
            hooks=AgentHooks(
                prepare_step=self.prepare_step,
                build_request=self.build_request,
                after_step=self.after_step,
            ),
        )

    @property
    def input_messages(self) -> list[Message]:
        return [UserMessage(content=f"Repository: {self.repo}\n\nQuery:\n{self.query}")]

    def prepare_step(self, context: AgentContext, step: AgentStep) -> AgentContext:
        self.is_final_step = self.requested_final or step.is_last
        if self.is_final_step:
            self._system_prompt = CODING_AGENT_FINAL_ANSWER_PROMPT
            context.tools = []
            context.options.tool_choice = ToolChoiceOptions.NONE
        else:
            template = (
                CODING_AGENT_PROMPT_REASONING
                if self.is_reasoning_model
                else CODING_AGENT_PROMPT
            )
            self._system_prompt = template.format(
                current_datetime=get_current_llm_day_time(full_sentence=False),
                current_cycle_count=step.index,
            )
            context.tools = [
                self._tool(BASH_TOOL_DESCRIPTION, self._bash),
                self._tool(GENERATE_ANSWER_TOOL_DESCRIPTION, self._request_answer),
            ]
            if not self.is_reasoning_model:
                context.tools.append(
                    self._tool(CODING_AGENT_THINK_TOOL_DESCRIPTION, self._think)
                )
            context.options.tool_choice = ToolChoiceOptions.REQUIRED
        context.options.max_tokens = (
            MAX_FINAL_ANSWER_TOKENS if self.is_final_step else MAX_INVESTIGATION_TOKENS
        )
        context.options.reasoning_effort = ReasoningEffort.LOW
        return context

    def build_request(self, context: AgentContext) -> GenerationRequest:
        prompt = self._system_prompt
        reminder = USER_FINAL_ANSWER_QUERY.format(query=self.query, repo=self.repo)
        messages = prepare_prompt(
            token_counter=self.token_counter,
            system_prompt=SystemMessage(
                content=prompt,
                metadata=PromptMetadata(token_count=self.token_counter(prompt)),
            ),
            custom_agent_prompt=None,
            messages=context.messages,
            reminder_message=UserMessage(
                content=reminder,
                metadata=PromptMetadata(token_count=self.token_counter(reminder)),
            )
            if self.is_final_step
            else None,
            context_files=None,
        )
        context.messages = prepare_model_messages(messages, self.llm.info)
        return context.generation_request()

    def after_step(self, result: StepResult) -> bool:
        if self.is_final_step:
            return False
        if not result.message.tool_calls or any(
            call.name == GENERATE_ANSWER_TOOL_NAME for call in result.message.tool_calls
        ):
            self.requested_final = True
        return True

    def _tool(
        self,
        definition: FunctionToolDefinition,
        execute: Callable[[ToolInvocation], ToolResult],
    ) -> AgentTool:
        function = definition["function"]
        return AgentTool(
            name=function["name"],
            description=function["description"],
            parameters=function["parameters"],
            execute=execute,
            execution_mode=ToolExecutionMode.SEQUENTIAL,
        )

    def _bash(self, invocation: ToolInvocation) -> ToolResult:
        return run_tool(self.bash_tool, invocation, ToolContext())

    @staticmethod
    def _request_answer(_invocation: ToolInvocation) -> ToolResult:
        return ToolResult(content="Ready to produce the final answer.")

    @staticmethod
    def _think(_invocation: ToolInvocation) -> ToolResult:
        return ToolResult(content=THINK_TOOL_RESPONSE_MESSAGE)
