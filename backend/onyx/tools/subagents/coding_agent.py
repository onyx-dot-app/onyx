import asyncio
import time
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from typing import Callable

from pydantic_ai import RunContext

from onyx.chat.emitter import Emitter
from onyx.coding_agent.mock_tools import (
    BASH_TOOL_CMD_KEY,
    BASH_TOOL_NAME,
    CODING_AGENT_QUERY_KEY,
    CODING_AGENT_REPO_KEY,
    GENERATE_ANSWER_TOOL_NAME,
    get_coding_agent_tool_definitions,
)
from onyx.coding_agent.models import CodingAgentCallResult
from onyx.deep_research.dr_mock_tools import (
    THINK_TOOL_NAME,
    THINK_TOOL_RESPONSE_MESSAGE,
)
from onyx.llm.interfaces import LLM, LLMUserIdentity
from onyx.llm.model_capabilities import model_is_reasoning_model
from onyx.llm.models import ReasoningEffort, ToolChoiceOptions
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
    PacketException,
    StreamingType,
)
from onyx.tools.models import ToolCallKickoff
from onyx.tools.progress import check_tool_run_active
from onyx.tools.tool_implementations.bash.bash_tool import (
    BashTool,
    BashToolOverrideKwargs,
)
from onyx.tools.tool_implementations.python.code_interpreter_client import (
    CodeInterpreterClient,
)
from onyx.tracing.framework.create import function_span
from onyx.utils.github import download_github_archive, parse_github_source
from onyx.utils.logger import setup_logger

logger = setup_logger()


# Allow up to an hour for the agent to investigate the repo
CODING_AGENT_SESSION_TTL_SECONDS = 60 * 60
# Per-bash-command timeout. Capped at the code-interpreter service's
# max_exec_timeout_ms (60s by default; configurable via MAX_EXEC_TIMEOUT_MS).
CODING_AGENT_BASH_TIMEOUT_MS = 60 * 1000
# Hard wall-clock timeout for the whole agent run
CODING_AGENT_FORCE_ANSWER_SECONDS = 25 * 60
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
        len(response.llm_facing_response),
    )
    return response.llm_facing_response


@asynccontextmanager
async def _async_setup_session(
    repo: str, github_token: str | None
) -> AsyncIterator[str]:
    session = _setup_session(repo=repo, github_token=github_token)
    setup = asyncio.create_task(asyncio.to_thread(session.__enter__))
    try:
        session_id = await asyncio.shield(setup)
    except asyncio.CancelledError:
        await setup
        await asyncio.to_thread(session.__exit__, None, None, None)
        raise
    try:
        yield session_id
    finally:
        await asyncio.to_thread(session.__exit__, None, None, None)


async def run_coding_agent_call(
    parent_context: RunContext[None] | None,
    coding_agent_call: ToolCallKickoff,
    emitter: Emitter,
    llm: LLM,
    token_counter: Callable[[str], int],
    user_identity: LLMUserIdentity | None,
    github_token: str | None = None,
) -> CodingAgentCallResult | None:
    turn_index = coding_agent_call.placement.turn_index
    tab_index = coding_agent_call.placement.tab_index
    is_reasoning_model = model_is_reasoning_model(
        llm.config.model_name, llm.config.model_provider
    )

    with function_span("coding_agent") as span:
        span.span_data.input = str(coding_agent_call.tool_args)
        try:
            query = coding_agent_call.tool_args[CODING_AGENT_QUERY_KEY]
            repo = coding_agent_call.tool_args[CODING_AGENT_REPO_KEY]

            async with _async_setup_session(
                repo=repo, github_token=github_token
            ) as session_id:
                bash_tool = BashTool(
                    tool_id=BASH_TOOL_SENTINEL_ID,
                    session_id=session_id,
                    emitter=emitter,
                )

                from pydantic_ai.messages import (
                    ModelMessage,
                    ModelRequest,
                    ModelResponse,
                    SystemPromptPart,
                    ToolCallPart,
                    UserPromptPart,
                )
                from pydantic_ai.tools import ToolDefinition

                from onyx.chat.agent_runtime import (
                    NativeAgentRequest,
                    build_native_agent,
                )
                from onyx.llm.pydantic_ai_llm import PydanticAILLM

                if not isinstance(llm, PydanticAILLM):
                    raise TypeError("Coding agents require a Pydantic AI model")
                start_time = time.monotonic()
                cycle_count = 0
                completed_response = False
                report_requested = False
                calls: list[ToolCallKickoff] = []
                definitions = get_coding_agent_tool_definitions(
                    include_think_tool=not is_reasoning_model
                )
                native_tools = [
                    ToolDefinition(
                        name=definition["function"]["name"],
                        description=definition["function"].get("description"),
                        parameters_json_schema=definition["function"]["parameters"],
                    )
                    for definition in definitions
                ]

                def placement() -> Placement:
                    return Placement(
                        turn_index=turn_index,
                        tab_index=tab_index,
                        sub_turn_index=cycle_count,
                    )

                def prepare_step(messages: list[ModelMessage]) -> NativeAgentRequest:
                    nonlocal report_requested, completed_response, cycle_count
                    if completed_response:
                        cycle_count += 1
                        completed_response = False
                    report_requested = (
                        report_requested
                        or cycle_count >= MAX_CODING_AGENT_CYCLES
                        or time.monotonic() - start_time
                        >= CODING_AGENT_FORCE_ANSWER_SECONDS
                    )
                    template = (
                        CODING_AGENT_PROMPT_REASONING
                        if is_reasoning_model
                        else CODING_AGENT_PROMPT
                    )
                    prompt = (
                        CODING_AGENT_FINAL_ANSWER_PROMPT
                        if report_requested
                        else template.format(
                            current_datetime=get_current_llm_day_time(
                                full_sentence=False
                            ),
                            current_cycle_count=cycle_count,
                        )
                    )
                    history = [
                        message
                        for message in messages
                        if not (
                            isinstance(message, ModelRequest)
                            and all(
                                isinstance(part, SystemPromptPart)
                                for part in message.parts
                            )
                        )
                    ]
                    history.insert(0, ModelRequest(parts=[SystemPromptPart(prompt)]))
                    if report_requested:
                        history.append(
                            ModelRequest(
                                parts=[
                                    UserPromptPart(
                                        USER_FINAL_ANSWER_QUERY.format(
                                            query=query, repo=repo
                                        )
                                    )
                                ]
                            )
                        )
                    return NativeAgentRequest(
                        messages=history,
                        settings=llm.model_settings(
                            reasoning_effort=ReasoningEffort.LOW,
                            max_tokens=MAX_FINAL_ANSWER_TOKENS
                            if report_requested
                            else 2048,
                            user_identity=user_identity,
                            tool_choice=ToolChoiceOptions.NONE
                            if report_requested
                            else ToolChoiceOptions.REQUIRED,
                        ),
                        tools=[] if report_requested else native_tools,
                    )

                def finalize_step(response: ModelResponse) -> None:
                    nonlocal calls, completed_response
                    completed_response = True
                    calls = [
                        ToolCallKickoff(
                            tool_call_id=part.tool_call_id,
                            tool_name=part.tool_name,
                            tool_args=part.args_as_dict(),
                            placement=placement(),
                        )
                        for part in response.parts
                        if isinstance(part, ToolCallPart)
                    ]

                def execute_tool(native_call: ToolCallPart) -> str:
                    nonlocal report_requested
                    results: dict[str, str] = {}
                    for call in [
                        ToolCallKickoff(
                            tool_call_id=native_call.tool_call_id,
                            tool_name=native_call.tool_name,
                            tool_args=native_call.args_as_dict(),
                            placement=next(
                                (
                                    item.placement
                                    for item in calls
                                    if item.tool_call_id == native_call.tool_call_id
                                ),
                                placement(),
                            ),
                        )
                    ]:
                        if call.tool_name == GENERATE_ANSWER_TOOL_NAME:
                            report_requested = True
                            results[call.tool_call_id] = "Produce the final answer."
                        elif call.tool_name == THINK_TOOL_NAME:
                            results[call.tool_call_id] = THINK_TOOL_RESPONSE_MESSAGE
                        elif call.tool_name == BASH_TOOL_NAME:
                            results[call.tool_call_id] = _run_bash_call(bash_tool, call)
                    check_tool_run_active()
                    return results.get(
                        native_call.tool_call_id, "Tool execution produced no result."
                    )

                child = build_native_agent(
                    agent_name="coding_agent",
                    llm=llm,
                    prepare_step=prepare_step,
                    finalize_step=finalize_step,
                    execute_tool=execute_tool,
                    tool_definitions=definitions,
                    max_requests=MAX_CODING_AGENT_CYCLES + 2,
                    sequential_tool_names=frozenset({BASH_TOOL_NAME}),
                    event_phase=lambda: "coding",
                    tokenizer=token_counter,
                    emitter=emitter,
                    state_container=None,
                    placement=placement,
                    message_history=[],
                )
                task = f"Repository: {repo}\n\nQuery:\n{query}"
                final_answer = (
                    await child.delegate(parent_context, task)
                    if parent_context is not None
                    else await child.run(task)
                )
                span.span_data.output = final_answer
                await asyncio.to_thread(
                    emitter.report,
                    placement=Placement(turn_index=turn_index, tab_index=tab_index),
                    obj=CodingAgentFinal(answer=final_answer),
                )
                return CodingAgentCallResult(answer=final_answer)
        except Exception as e:
            logger.exception("Error running coding agent call: %s", e)
            await asyncio.to_thread(
                emitter.report,
                placement=Placement(turn_index=turn_index, tab_index=tab_index),
                obj=PacketException(type=StreamingType.ERROR.value, exception=e),
            )
            return None
