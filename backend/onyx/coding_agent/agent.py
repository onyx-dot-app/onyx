import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Callable

from onyx.agents.runtime import Agent, AgentContext, AgentHooks, AgentTurn, TurnResult
from onyx.chat.emitter import Emitter, NullEmitter
from onyx.chat.presentation import TurnPresentation
from onyx.chat.renderer import RenderConfig
from onyx.coding_agent.models import CodingAgentCallResult
from onyx.coding_agent.tool_definitions import (
    BASH_TOOL_CMD_KEY,
    BASH_TOOL_NAME,
    CODING_AGENT_QUERY_KEY,
    CODING_AGENT_REPO_KEY,
    GENERATE_ANSWER_TOOL_NAME,
    get_coding_agent_tool_definitions,
)
from onyx.context.messages import PromptMetadata, prepare_model_messages
from onyx.context.prompt import prepare_prompt
from onyx.deep_research.tool_definitions import (
    THINK_TOOL_NAME,
    THINK_TOOL_RESPONSE_MESSAGE,
)
from onyx.llm.cancellation import (
    CancellationSignal,
    cancellation_scope,
    check_cancelled,
    current_cancellation,
)
from onyx.llm.interfaces import LLM, GenerationContext, LLMUserIdentity
from onyx.llm.model_capabilities import model_is_reasoning_model
from onyx.llm.models import (
    Message,
    ReasoningEffort,
    SystemMessage,
    ToolCall,
    ToolChoiceOptions,
    ToolResult,
    UserMessage,
)
from onyx.prompts.coding_agent.coding_agent import (
    CODING_AGENT_FINAL_ANSWER_PROMPT,
    CODING_AGENT_PROMPT,
    CODING_AGENT_PROMPT_REASONING,
    MAX_CODING_AGENT_CYCLES,
    USER_FINAL_ANSWER_QUERY,
)
from onyx.prompts.prompt_utils import get_current_llm_day_time
from onyx.server.query_and_chat.placement import Placement
from onyx.server.query_and_chat.streaming_models import (
    CodingAgentFinal,
    Packet,
    PacketException,
    StreamingType,
)
from onyx.tools.models import ToolCallKickoff
from onyx.tools.tool_implementations.bash.bash_tool import (
    BashTool,
    BashToolOverrideKwargs,
)
from onyx.tools.tool_implementations.python.code_interpreter_client import (
    CodeInterpreterClient,
)
from onyx.tools.tool_runner import LegacyToolContext, bind_tool
from onyx.tracing.flows import LLMFlow
from onyx.tracing.framework.create import function_span
from onyx.utils.github import download_github_archive, parse_github_source
from onyx.utils.logger import setup_logger

logger = setup_logger()


# Sandbox session lifetime; this does not limit agent execution time.
CODING_AGENT_SESSION_TTL_SECONDS = 60 * 60
# Per-bash-command timeout. Capped at the code-interpreter service's
# max_exec_timeout_ms (60s by default; configurable via MAX_EXEC_TIMEOUT_MS).
CODING_AGENT_BASH_TIMEOUT_MS = 60 * 1000
# Same cap applies to setup commands (tarball extract). If a repo extract
# legitimately takes more than 60s, raise MAX_EXEC_TIMEOUT_MS on the
# code-interpreter service rather than this constant.
CODING_AGENT_SETUP_TIMEOUT_MS = 60 * 1000
# Tarball is staged at this path inside the session workspace
REPO_TARBALL_PATH = "repo.tar.gz"
# Sentinel tool_id used when constructing the in-memory BashTool. Bash sub-tool
# calls are not persisted to the DB through this loop, so the id is unused.
BASH_TOOL_SENTINEL_ID = 0
MAX_FINAL_ANSWER_TOKENS = 4000
CODING_AGENT_GITHUB_MAX_REPO_BYTES = 500 * 1024 * 1024
CODING_AGENT_GITHUB_DOWNLOAD_TIMEOUT = (30, 300)


@contextmanager
def _setup_session(
    repo: str,
    github_token: str | None,
) -> Iterator[str]:
    """Download ``repo``, create a code-interpreter session with the tarball
    staged + extracted, yield the session id, and delete the session on exit.

    Creates its own :class:`CodeInterpreterClient` internally and tears it
    down on exit, so callers only deal with the ``session_id``.
    """
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
            yield session_id
        finally:
            try:
                client.delete_session(session_id)
                logger.info("Deleted coding agent session %s", session_id)
            except Exception as e:
                # Don't let cleanup failure mask any exception from the body.
                # The session has a TTL so the pod will eventually be reaped.
                logger.warning(
                    "Failed to delete coding agent session %s: %s", session_id, e
                )


def _run_bash_call(
    bash_tool: BashTool,
    tool_call: ToolCallKickoff,
) -> str:
    """Dispatch a single bash tool call and return the LLM-facing response."""
    cmd = tool_call.tool_args.get(BASH_TOOL_CMD_KEY)
    if not isinstance(cmd, str):
        logger.warning(
            "[coding_agent] bash tool call %s missing/non-string %r argument; got %r",
            tool_call.tool_call_id,
            BASH_TOOL_CMD_KEY,
            cmd,
        )
        return f'{{"error": "missing or non-string {BASH_TOOL_CMD_KEY!r} argument"}}'

    logger.info(
        "[coding_agent] bash %s: %s",
        tool_call.tool_call_id,
        cmd,
    )
    start = time.monotonic()
    response = bash_tool.run(
        placement=tool_call.placement,
        override_kwargs=BashToolOverrideKwargs(),
        **{BASH_TOOL_CMD_KEY: cmd},
    )
    duration_ms = int((time.monotonic() - start) * 1000)
    logger.info(
        "[coding_agent] bash %s done in %dms (response %d chars)",
        tool_call.tool_call_id,
        duration_ms,
        len(response.text),
    )
    return response.text


class CodingAgent(Agent):
    """Repository investigation policy; Agent owns scheduling and cancellation."""

    def __init__(
        self,
        coding_agent_call: ToolCall,
        emitter: Emitter | None,
        llm: LLM,
        token_counter: Callable[[str], int],
        user_identity: LLMUserIdentity | None,
        bash_tool: BashTool,
        *,
        display_placement: Placement | None = None,
    ) -> None:
        self.emitter = emitter or NullEmitter()
        self.llm = llm
        self.token_counter = token_counter
        self.user_identity = user_identity
        self.bash_tool = bash_tool
        self.query = str(coding_agent_call.arguments[CODING_AGENT_QUERY_KEY])
        self.repo = str(coding_agent_call.arguments[CODING_AGENT_REPO_KEY])
        display_placement = display_placement or Placement(turn_index=0)
        self.turn_index = display_placement.turn_index
        self.tab_index = display_placement.tab_index
        self.is_reasoning_model = model_is_reasoning_model(
            llm.info.model_name, llm.info.model_provider
        )
        message = f"Repository: {self.repo}\n\nQuery:\n{self.query}"
        messages: list[Message] = [
            UserMessage(
                content=message,
                metadata=PromptMetadata(token_count=token_counter(message)),
            )
        ]
        self.llm_cycle_count = 0
        self.reasoning_cycles = 0

        self.turn = AgentTurn(index=0, limit=1)
        self.requested_final = False
        self.is_final_turn = False
        self.presentation = TurnPresentation(emitter) if emitter is not None else None
        super().__init__(
            self.llm,
            context=AgentContext(
                messages=messages,
                execution=GenerationContext(flow=LLMFlow.CODING_AGENT),
            ),
            hooks=AgentHooks(
                transform_context=self._context, after_turn=self._after_turn
            ),
        )
        self.tool_context = LegacyToolContext(lambda: self.context.messages)
        if self.presentation is not None:
            self.subscribe(self.presentation.consume)

    def _context(self, context: AgentContext, turn: AgentTurn) -> AgentContext:
        self.turn = turn
        self.is_final_turn = self.requested_final or turn.is_last
        if self.is_final_turn:
            context.tools = []
            context.options.tool_choice = ToolChoiceOptions.NONE
        else:
            definitions = get_coding_agent_tool_definitions(
                include_think_tool=not self.is_reasoning_model
            )
            context.tools = [
                bind_tool(
                    definition,
                    self._execute_tool,
                    self.tool_context,
                    sequential=True,
                )
                for definition in definitions
            ]
            context.options.tool_choice = ToolChoiceOptions.REQUIRED
        placement = Placement(
            turn_index=self.turn_index,
            tab_index=self.tab_index,
            sub_turn_index=self.llm_cycle_count + self.reasoning_cycles,
        )
        history = (
            self.prepare(turn)
            if not self.is_final_turn
            else prepare_prompt(
                token_counter=self.token_counter,
                system_prompt=SystemMessage(
                    content=CODING_AGENT_FINAL_ANSWER_PROMPT,
                    metadata=PromptMetadata(
                        token_count=self.token_counter(CODING_AGENT_FINAL_ANSWER_PROMPT)
                    ),
                ),
                custom_agent_prompt=None,
                messages=self.context.messages,
                reminder_message=UserMessage(
                    content=USER_FINAL_ANSWER_QUERY.format(
                        query=self.query, repo=self.repo
                    ),
                    metadata=PromptMetadata(token_count=100),
                ),
                context_files=None,
                available_tokens=self.llm.info.max_input_tokens,
            )
        )
        context.options.max_tokens = (
            MAX_FINAL_ANSWER_TOKENS if self.is_final_turn else 2048
        )
        context.options.reasoning_effort = ReasoningEffort.LOW
        config = RenderConfig(
            placement=placement,
            nested=True,
            mode="silent" if self.is_final_turn else "coding_thinking",
            think_tool=THINK_TOOL_NAME if not self.is_reasoning_model else None,
        )
        if self.presentation is not None:
            self.presentation.configure(config)
        context.execution.user_identity = self.user_identity
        context.messages = history
        context.messages = prepare_model_messages(context.messages, self.llm.info)
        return context

    def prepare(self, turn: AgentTurn) -> list[Message]:
        system_prompt_template = (
            CODING_AGENT_PROMPT_REASONING
            if self.is_reasoning_model
            else CODING_AGENT_PROMPT
        )
        system_prompt_str = system_prompt_template.format(
            current_datetime=get_current_llm_day_time(full_sentence=False),
            current_cycle_count=turn.index,
        )
        system_prompt = SystemMessage(
            content=system_prompt_str,
            metadata=PromptMetadata(token_count=self.token_counter(system_prompt_str)),
        )

        constructed_history = prepare_prompt(
            token_counter=self.token_counter,
            system_prompt=system_prompt,
            custom_agent_prompt=None,
            messages=self.context.messages,
            reminder_message=None,
            context_files=None,
            available_tokens=self.llm.info.max_input_tokens,
        )

        return constructed_history

    def _execute_tool(self, call: ToolCallKickoff) -> ToolResult:
        if call.tool_name == GENERATE_ANSWER_TOOL_NAME:
            self.requested_final = True
            return ToolResult(content="Ready to produce the final answer.")
        if call.tool_name == THINK_TOOL_NAME:
            return ToolResult(content=THINK_TOOL_RESPONSE_MESSAGE)
        return ToolResult(content=_run_bash_call(self.bash_tool, call))

    def _after_turn(self, result: TurnResult) -> None:
        self.reasoning_cycles += int(
            bool(result.message.thinking)
            or any(call.name == THINK_TOOL_NAME for call in result.message.tool_calls)
        )
        if self.is_final_turn:
            return
        if any(call.name == BASH_TOOL_NAME for call in result.message.tool_calls):
            self.llm_cycle_count += 1
        if not result.message.tool_calls:
            self.requested_final = True
            self.follow_up(
                UserMessage(content="Produce the final answer from the investigation.")
            )


def run_coding_agent_call(
    coding_agent_call: ToolCallKickoff,
    emitter: Emitter | None,
    llm: LLM,
    token_counter: Callable[[str], int],
    user_identity: LLMUserIdentity | None,
    github_token: str | None = None,
) -> CodingAgentCallResult | None:
    agent_emitter = emitter
    emitter = emitter or NullEmitter()
    turn_index = coding_agent_call.placement.turn_index
    tab_index = coding_agent_call.placement.tab_index
    with (
        cancellation_scope(current_cancellation() or CancellationSignal()),
        function_span("coding_agent") as span,
    ):
        span.span_data.input = str(coding_agent_call.tool_args)
        try:
            check_cancelled()
            repo = coding_agent_call.tool_args[CODING_AGENT_REPO_KEY]

            with _setup_session(repo=repo, github_token=github_token) as session_id:
                bash_tool = BashTool(
                    tool_id=BASH_TOOL_SENTINEL_ID,
                    session_id=session_id,
                    emitter=emitter,
                )

                agent = CodingAgent(
                    ToolCall(
                        id=coding_agent_call.tool_call_id,
                        name=coding_agent_call.tool_name,
                        arguments=coding_agent_call.tool_args,
                    ),
                    agent_emitter,
                    llm,
                    token_counter,
                    user_identity,
                    bash_tool,
                    display_placement=coding_agent_call.placement,
                )
                completed = agent.run(max_turns=MAX_CODING_AGENT_CYCLES + 1)
                check_cancelled()
                answer = completed.output.text
                if not answer:
                    raise ValueError("Model failed to produce a final answer")
                emitter.emit(
                    Packet(
                        placement=Placement(turn_index=turn_index, tab_index=tab_index),
                        obj=CodingAgentFinal(answer=answer),
                    )
                )
                result = CodingAgentCallResult(answer=answer)
                span.span_data.output = result.answer
                return result
        except Exception as e:
            logger.exception("Error running coding agent call: %s", e)
            emitter.emit(
                Packet(
                    placement=Placement(turn_index=turn_index, tab_index=tab_index),
                    obj=PacketException(type=StreamingType.ERROR.value, exception=e),
                )
            )
            return None
