import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Callable

from onyx.chat.emitter import Emitter
from onyx.chat.llm_loop import construct_message_history
from onyx.chat.llm_step import run_llm_step_pkt_generator
from onyx.chat.models import ChatMessageSimple
from onyx.chat.models import ToolCallSimple
from onyx.coding_agent.mock_tools import BASH_TOOL_CMD_KEY
from onyx.coding_agent.mock_tools import BASH_TOOL_NAME
from onyx.coding_agent.mock_tools import CODING_AGENT_QUERY_KEY
from onyx.coding_agent.mock_tools import CODING_AGENT_REPO_KEY
from onyx.coding_agent.mock_tools import GENERATE_ANSWER_TOOL_NAME
from onyx.coding_agent.mock_tools import get_coding_agent_tool_definitions
from onyx.coding_agent.models import CodingAgentCallResult
from onyx.coding_agent.models import CodingAgentSpecialToolCalls
from onyx.configs.constants import MessageType
from onyx.deep_research.dr_mock_tools import THINK_TOOL_NAME
from onyx.deep_research.dr_mock_tools import THINK_TOOL_RESPONSE_MESSAGE
from onyx.deep_research.dr_mock_tools import THINK_TOOL_RESPONSE_TOKEN_COUNT
from onyx.deep_research.utils import create_think_tool_token_processor
from onyx.llm.interfaces import LLM
from onyx.llm.interfaces import LLMUserIdentity
from onyx.llm.models import ReasoningEffort
from onyx.llm.models import ToolChoiceOptions
from onyx.llm.utils import model_is_reasoning_model
from onyx.prompts.coding_agent.coding_agent import CODING_AGENT_FINAL_ANSWER_PROMPT
from onyx.prompts.coding_agent.coding_agent import CODING_AGENT_PROMPT
from onyx.prompts.coding_agent.coding_agent import CODING_AGENT_PROMPT_REASONING
from onyx.prompts.coding_agent.coding_agent import MAX_CODING_AGENT_CYCLES
from onyx.prompts.coding_agent.coding_agent import USER_FINAL_ANSWER_QUERY
from onyx.prompts.prompt_utils import get_current_llm_day_time
from onyx.server.query_and_chat.placement import Placement
from onyx.server.query_and_chat.streaming_models import AgentResponseDelta
from onyx.server.query_and_chat.streaming_models import AgentResponseStart
from onyx.server.query_and_chat.streaming_models import CodingAgentFinal
from onyx.server.query_and_chat.streaming_models import CodingAgentThinkingDelta
from onyx.server.query_and_chat.streaming_models import Packet
from onyx.server.query_and_chat.streaming_models import PacketException
from onyx.server.query_and_chat.streaming_models import StreamingType
from onyx.tools.models import ToolCallKickoff
from onyx.tools.tool_implementations.bash.bash_tool import BashTool
from onyx.tools.tool_implementations.bash.bash_tool import BashToolOverrideKwargs
from onyx.tools.tool_implementations.python.code_interpreter_client import (
    CodeInterpreterClient,
)
from onyx.tracing.framework.create import function_span
from onyx.utils.github import download_github_repo
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
    repo_bytes = download_github_repo(repo, github_token=github_token)

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
            "[coding_agent] bash tool call %s missing/non-string %r argument; "
            "got %r",
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


def _generate_final_answer(
    query: str,
    repo: str,
    history: list[ChatMessageSimple],
    llm: LLM,
    token_counter: Callable[[str], int],
    user_identity: LLMUserIdentity | None,
    emitter: Emitter,
    placement: Placement,
) -> str:
    """Run a final, no-tool LLM step that produces the user-facing answer."""
    with function_span("generate_coding_agent_answer") as span:
        span.span_data.input = f"history_length={len(history)}"
        system_prompt = ChatMessageSimple(
            message=CODING_AGENT_FINAL_ANSWER_PROMPT,
            token_count=token_counter(CODING_AGENT_FINAL_ANSWER_PROMPT),
            message_type=MessageType.SYSTEM,
        )
        reminder_str = USER_FINAL_ANSWER_QUERY.format(query=query, repo=repo)
        reminder_message = ChatMessageSimple(
            message=reminder_str,
            token_count=token_counter(reminder_str),
            message_type=MessageType.USER,
        )

        final_history = construct_message_history(
            system_prompt=system_prompt,
            custom_agent_prompt=None,
            simple_chat_history=history,
            reminder_message=reminder_message,
            context_files=None,
            available_tokens=llm.config.max_input_tokens,
        )

        answer_generator = run_llm_step_pkt_generator(
            history=final_history,
            tool_definitions=[],
            tool_choice=ToolChoiceOptions.NONE,
            llm=llm,
            placement=placement,
            citation_processor=None,
            state_container=None,
            reasoning_effort=ReasoningEffort.LOW,
            final_documents=None,
            user_identity=user_identity,
            max_tokens=MAX_FINAL_ANSWER_TOKENS,
            use_existing_tab_index=True,
            is_deep_research=False,
        )

        while True:
            try:
                packet = next(answer_generator)
                if isinstance(packet.obj, (AgentResponseStart, AgentResponseDelta)):
                    continue
                emitter.emit(Packet(placement=placement, obj=packet.obj))
            except StopIteration as e:
                llm_step_result, _ = e.value
                break

        final_answer = llm_step_result.answer
        if not final_answer:
            raise ValueError("LLM failed to produce a final answer")
        span.span_data.output = final_answer
        return final_answer


def _check_special_tool_calls(
    tool_calls: list[ToolCallKickoff],
) -> CodingAgentSpecialToolCalls:
    think_tool_call: ToolCallKickoff | None = None
    generate_answer_tool_call: ToolCallKickoff | None = None

    for tool_call in tool_calls:
        if tool_call.tool_name == THINK_TOOL_NAME:
            think_tool_call = tool_call
        elif tool_call.tool_name == GENERATE_ANSWER_TOOL_NAME:
            generate_answer_tool_call = tool_call

    return CodingAgentSpecialToolCalls(
        think_tool_call=think_tool_call,
        generate_answer_tool_call=generate_answer_tool_call,
    )


def run_coding_agent_call(
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

            with _setup_session(repo=repo, github_token=github_token) as session_id:
                bash_tool = BashTool(
                    tool_id=BASH_TOOL_SENTINEL_ID,
                    session_id=session_id,
                    emitter=emitter,
                )

                initial_user_message = ChatMessageSimple(
                    message=(f"Repository: {repo}\n\nQuery:\n{query}"),
                    token_count=token_counter(f"Repository: {repo}\n\nQuery:\n{query}"),
                    message_type=MessageType.USER,
                )
                msg_history: list[ChatMessageSimple] = [initial_user_message]

                start_time = time.monotonic()
                cycle_count = 0
                llm_cycle_count = 0
                reasoning_cycles = 0
                most_recent_reasoning: str | None = None

                while cycle_count < MAX_CODING_AGENT_CYCLES:
                    elapsed = time.monotonic() - start_time
                    if elapsed > CODING_AGENT_FORCE_ANSWER_SECONDS:
                        logger.info(
                            "Coding agent exceeded %ss (elapsed: %.1fs); "
                            "forcing final answer.",
                            CODING_AGENT_FORCE_ANSWER_SECONDS,
                            elapsed,
                        )
                        break

                    system_prompt_template = (
                        CODING_AGENT_PROMPT_REASONING
                        if is_reasoning_model
                        else CODING_AGENT_PROMPT
                    )
                    system_prompt_str = system_prompt_template.format(
                        current_datetime=get_current_llm_day_time(full_sentence=False),
                        current_cycle_count=cycle_count,
                    )
                    system_prompt = ChatMessageSimple(
                        message=system_prompt_str,
                        token_count=token_counter(system_prompt_str),
                        message_type=MessageType.SYSTEM,
                    )

                    constructed_history = construct_message_history(
                        system_prompt=system_prompt,
                        custom_agent_prompt=None,
                        simple_chat_history=msg_history,
                        reminder_message=None,
                        context_files=None,
                        available_tokens=llm.config.max_input_tokens,
                    )

                    custom_processor = (
                        create_think_tool_token_processor()
                        if not is_reasoning_model
                        else None
                    )

                    step_placement = Placement(
                        turn_index=turn_index,
                        tab_index=tab_index,
                        sub_turn_index=llm_cycle_count + reasoning_cycles,
                    )
                    step_generator = run_llm_step_pkt_generator(
                        history=constructed_history,
                        tool_definitions=get_coding_agent_tool_definitions(
                            include_think_tool=not is_reasoning_model
                        ),
                        tool_choice=ToolChoiceOptions.REQUIRED,
                        llm=llm,
                        placement=step_placement,
                        citation_processor=None,
                        state_container=None,
                        reasoning_effort=ReasoningEffort.LOW,
                        final_documents=None,
                        user_identity=user_identity,
                        custom_token_processor=custom_processor,
                        use_existing_tab_index=True,
                        is_deep_research=False,
                        max_tokens=2048,
                    )

                    while True:
                        try:
                            packet = next(step_generator)
                            if isinstance(
                                packet.obj,
                                (AgentResponseStart, AgentResponseDelta),
                            ):
                                if isinstance(packet.obj, AgentResponseDelta):
                                    emitter.emit(
                                        Packet(
                                            placement=step_placement,
                                            obj=CodingAgentThinkingDelta(
                                                content=packet.obj.content
                                            ),
                                        )
                                    )
                            else:
                                emitter.emit(packet)
                        except StopIteration as e:
                            llm_step_result, has_reasoned = e.value
                            break

                    if has_reasoned:
                        reasoning_cycles += 1

                    tool_calls = llm_step_result.tool_calls or []
                    if not tool_calls:
                        logger.warning(
                            "Coding agent LLM produced no tool calls; "
                            "forcing final answer."
                        )
                        break

                    special = _check_special_tool_calls(tool_calls)

                    if special.generate_answer_tool_call:
                        break

                    if special.think_tool_call:
                        think_tool_call = special.think_tool_call
                        tool_call_message = think_tool_call.to_msg_str()
                        tool_call_token_count = token_counter(tool_call_message)
                        think_assistant_msg = ChatMessageSimple(
                            message="",
                            token_count=tool_call_token_count,
                            message_type=MessageType.ASSISTANT,
                            tool_calls=[
                                ToolCallSimple(
                                    tool_call_id=think_tool_call.tool_call_id,
                                    tool_name=think_tool_call.tool_name,
                                    tool_arguments=think_tool_call.tool_args,
                                    token_count=tool_call_token_count,
                                )
                            ],
                            image_files=None,
                        )
                        msg_history.append(think_assistant_msg)
                        msg_history.append(
                            ChatMessageSimple(
                                message=THINK_TOOL_RESPONSE_MESSAGE,
                                token_count=THINK_TOOL_RESPONSE_TOKEN_COUNT,
                                message_type=MessageType.TOOL_CALL_RESPONSE,
                                tool_call_id=think_tool_call.tool_call_id,
                                image_files=None,
                            )
                        )
                        most_recent_reasoning = llm_step_result.reasoning
                        cycle_count += 1
                        continue

                    # Otherwise: dispatch all bash tool calls sequentially.
                    # Sequential is intentional — they share the session
                    # filesystem and ordering matters.
                    bash_calls = [
                        tc for tc in tool_calls if tc.tool_name == BASH_TOOL_NAME
                    ]
                    if not bash_calls:
                        logger.warning(
                            "Coding agent LLM emitted unexpected tool calls: %s",
                            [tc.tool_name for tc in tool_calls],
                        )
                        break

                    # Build ONE assistant message with all bash tool calls
                    tool_calls_simple: list[ToolCallSimple] = []
                    for tc in bash_calls:
                        msg_str = tc.to_msg_str()
                        tool_calls_simple.append(
                            ToolCallSimple(
                                tool_call_id=tc.tool_call_id,
                                tool_name=tc.tool_name,
                                tool_arguments=tc.tool_args,
                                token_count=token_counter(msg_str),
                            )
                        )
                    assistant_with_tools = ChatMessageSimple(
                        message="",
                        token_count=sum(tcs.token_count for tcs in tool_calls_simple),
                        message_type=MessageType.ASSISTANT,
                        tool_calls=tool_calls_simple,
                        image_files=None,
                    )
                    msg_history.append(assistant_with_tools)

                    for tc in bash_calls:
                        tool_response = _run_bash_call(bash_tool, tc)
                        msg_history.append(
                            ChatMessageSimple(
                                message=tool_response,
                                token_count=token_counter(tool_response),
                                message_type=MessageType.TOOL_CALL_RESPONSE,
                                tool_call_id=tc.tool_call_id,
                                image_files=None,
                            )
                        )

                    most_recent_reasoning = None
                    cycle_count += 1
                    llm_cycle_count += 1

                # Generate final answer
                final_answer = _generate_final_answer(
                    query=query,
                    repo=repo,
                    history=msg_history,
                    llm=llm,
                    token_counter=token_counter,
                    user_identity=user_identity,
                    emitter=emitter,
                    placement=Placement(turn_index=turn_index, tab_index=tab_index),
                )
                _ = most_recent_reasoning  # currently unused; kept for parity
                span.span_data.output = final_answer
                emitter.emit(
                    Packet(
                        placement=Placement(turn_index=turn_index, tab_index=tab_index),
                        obj=CodingAgentFinal(answer=final_answer),
                    )
                )
                return CodingAgentCallResult(answer=final_answer)
        except Exception as e:
            logger.exception("Error running coding agent call: %s", e)
            emitter.emit(
                Packet(
                    placement=Placement(turn_index=turn_index, tab_index=tab_index),
                    obj=PacketException(type=StreamingType.ERROR.value, exception=e),
                )
            )
            return None
