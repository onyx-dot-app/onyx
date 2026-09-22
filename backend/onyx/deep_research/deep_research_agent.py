# TODO: Notes for potential extensions and future improvements:
# 1. Allow tools that aren't search specific tools
# 2. Use user provided custom prompts
# 3. Save the plan for replay

import asyncio
import time
from collections.abc import Callable
from threading import Lock

from pydantic_ai import RunContext
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    SystemPromptPart,
    ThinkingPart,
    ToolCallPart,
    UserPromptPart,
)
from pydantic_ai.tools import ToolDefinition

from onyx.chat.chat_agent import construct_message_history
from onyx.chat.chat_state import ChatStateContainer
from onyx.chat.citation_processor import CitationMapping, DynamicCitationProcessor
from onyx.chat.citation_utils import collapse_citations
from onyx.chat.emitter import Emitter
from onyx.chat.models import (
    ChatMessageSimple,
    FileToolMetadata,
)
from onyx.chat.prompt_utils import build_language_section, with_language_section
from onyx.configs.chat_configs import (
    DR_REPORT_LLM_TIMEOUT_S,
    SKIP_DEEP_RESEARCH_CLARIFICATION,
)
from onyx.configs.constants import MessageType
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import SupportedLanguage
from onyx.db.tools import get_tool_by_name
from onyx.deep_research.dr_mock_tools import (
    RESEARCH_AGENT_TOOL_NAME,
    THINK_TOOL_RESPONSE_MESSAGE,
    get_clarification_tool_definitions,
    get_orchestrator_tools,
)
from onyx.llm.interfaces import LLM, LLMUserIdentity
from onyx.llm.model_capabilities import model_is_reasoning_model
from onyx.llm.models import ReasoningEffort, ToolChoiceOptions
from onyx.prompts.deep_research.orchestration_layer import (
    CLARIFICATION_PROMPT,
    FINAL_REPORT_PROMPT,
    FIRST_CYCLE_REMINDER,
    INTERNAL_SEARCH_CLARIFICATION_GUIDANCE,
    INTERNAL_SEARCH_RESEARCH_TASK_GUIDANCE,
    ORCHESTRATOR_PROMPT,
    ORCHESTRATOR_PROMPT_REASONING,
    RESEARCH_PLAN_PROMPT,
    RESEARCH_PLAN_REMINDER,
    USER_FINAL_REPORT_QUERY,
)
from onyx.prompts.prompt_utils import get_current_llm_day_time
from onyx.server.query_and_chat.placement import Placement
from onyx.server.query_and_chat.streaming_models import (
    DeepResearchPlanStart,
    OverallStop,
    TopLevelBranching,
)
from onyx.tools.interface import Tool
from onyx.tools.models import ToolCallInfo, ToolCallKickoff
from onyx.tools.progress import check_tool_run_active
from onyx.tools.subagents.research_agent import run_research_agent_call
from onyx.tools.tool_implementations.open_url.open_url_tool import OpenURLTool
from onyx.tools.tool_implementations.search.search_tool import SearchTool
from onyx.tools.tool_implementations.web_search.web_search_tool import WebSearchTool
from onyx.tracing.framework.create import ChatTraceMetadata, trace
from onyx.utils.logger import setup_logger
from onyx.utils.timing import log_function_time

logger = setup_logger()

MAX_USER_MESSAGES_FOR_CONTEXT = 5
MAX_FINAL_REPORT_TOKENS = 20000

# 30 minute timeout before forcing final report generation
# NOTE: The overall execution may be much longer still because it could run a research cycle at minute 29
# and that runs for another nearly 30 minutes.
DEEP_RESEARCH_FORCE_REPORT_SECONDS = 30 * 60

# Might be something like (this gives a lot of leeway for change but typically the models don't do this):
# 0. Research topics 1-3
# 1. Think
# 2. Research topics 4-5
# 3. Think
# 4. Research topics 6 + something new or different from the plan
# 5. Think
# 6. Research, possibly something new or different from the plan
# 7. Think
# 8. Generate report
MAX_ORCHESTRATOR_CYCLES = 8

# Similar but without the 4 thinking tool calls
MAX_ORCHESTRATOR_CYCLES_REASONING = 4


def _get_research_agent_tool_id() -> int:
    with get_session_with_current_tenant() as db_session:
        return get_tool_by_name(
            tool_name=RESEARCH_AGENT_TOOL_NAME,
            db_session=db_session,
        ).id


def replace_system(messages: list[ModelMessage], prompt: str) -> list[ModelMessage]:
    return [ModelRequest(parts=[SystemPromptPart(prompt)])] + [
        message
        for message in messages
        if not (
            isinstance(message, ModelRequest)
            and all(isinstance(part, SystemPromptPart) for part in message.parts)
        )
    ]


def native_definitions(definitions: list[dict]) -> list[ToolDefinition]:
    return [
        ToolDefinition(
            name=definition["function"]["name"],
            description=definition["function"].get("description"),
            parameters_json_schema=definition["function"]["parameters"],
        )
        for definition in definitions
    ]


def _plan_research(
    *,
    llm: LLM,
    emitter: Emitter,
    state_container: ChatStateContainer,
    native_history: list[ModelMessage],
    token_counter: Callable[[str], int],
    reasoning_effort: ReasoningEffort,
    user_identity: LLMUserIdentity | None,
    language_section: str,
    has_internal_search: bool,
    skip_clarification: bool,
) -> tuple[str, bool]:
    from onyx.chat.agent_runtime import NativeAgentRequest, run_native_agent
    from onyx.deep_research.dr_mock_tools import GENERATE_PLAN_TOOL_NAME

    planning = skip_clarification
    clarification_definitions = get_clarification_tool_definitions()

    plan_calls: list[ToolCallPart] = []
    plan_started = False

    def prepare_plan(messages: list[ModelMessage]) -> NativeAgentRequest:
        nonlocal plan_started
        if planning and not plan_started:
            emitter.report(
                placement=Placement(turn_index=0), obj=DeepResearchPlanStart()
            )
            plan_started = True
        prompt = (
            RESEARCH_PLAN_PROMPT.format(
                current_datetime=get_current_llm_day_time(full_sentence=False)
            )
            if planning
            else with_language_section(
                CLARIFICATION_PROMPT.format(
                    current_datetime=get_current_llm_day_time(full_sentence=False),
                    internal_search_clarification_guidance=INTERNAL_SEARCH_CLARIFICATION_GUIDANCE
                    if has_internal_search
                    else "",
                ),
                language_section,
            )
        )
        history = replace_system(messages, prompt)
        if planning:
            history.append(ModelRequest(parts=[UserPromptPart(RESEARCH_PLAN_REMINDER)]))
        return NativeAgentRequest(
            messages=history,
            settings=llm.model_settings(
                reasoning_effort=reasoning_effort,
                user_identity=user_identity,
                tool_choice=ToolChoiceOptions.NONE
                if planning
                else ToolChoiceOptions.AUTO,
            ),
            tools=[] if planning else native_definitions(clarification_definitions),
        )

    def finalize_plan(response: ModelResponse) -> None:
        nonlocal plan_calls
        plan_calls = [part for part in response.parts if isinstance(part, ToolCallPart)]

    def execute_plan_tool(native_call: ToolCallPart) -> str:
        nonlocal planning
        planning = native_call.tool_name == GENERATE_PLAN_TOOL_NAME
        return "Create the research plan."

    research_plan = run_native_agent(
        agent_name="research_planner",
        llm=llm,
        prepare_step=prepare_plan,
        finalize_step=finalize_plan,
        execute_tool=execute_plan_tool,
        tool_definitions=clarification_definitions,
        max_requests=3,
        event_phase=lambda: "plan" if planning else "clarification",
        tokenizer=token_counter,
        emitter=emitter,
        state_container=state_container,
        placement=lambda: Placement(turn_index=0),
        message_history=native_history,
    )
    return research_plan, planning


@log_function_time(print_only=True)
def run_deep_research_agent(
    emitter: Emitter,
    state_container: ChatStateContainer,
    simple_chat_history: list[ChatMessageSimple],
    tools: list[Tool],
    custom_agent_prompt: str | None,  # noqa: ARG001
    llm: LLM,
    token_counter: Callable[[str], int],
    user_language: SupportedLanguage | None,
    reasoning_effort: ReasoningEffort = ReasoningEffort.AUTO,
    skip_clarification: bool = False,
    user_identity: LLMUserIdentity | None = None,
    chat_session_id: str | None = None,
    all_injected_file_metadata: dict[str, FileToolMetadata] | None = None,
) -> None:
    with trace(
        "run_deep_research_agent",
        group_id=chat_session_id,
        metadata=ChatTraceMetadata(
            chat_session_id=chat_session_id,
            user_id=user_identity.user_id if user_identity else None,
        ).model_dump(),
    ):
        from onyx.chat.agent_runtime import NativeAgentRequest, run_native_agent
        from onyx.deep_research.dr_mock_tools import (
            GENERATE_REPORT_TOOL_NAME,
            THINK_TOOL_NAME,
        )
        from onyx.llm.pydantic_ai_llm import PydanticAILLM

        if not isinstance(llm, PydanticAILLM):
            raise TypeError("Deep research requires a Pydantic AI model")
        if llm.config.max_input_tokens < 50000:
            raise RuntimeError(
                "Cannot run Deep Research with an LLM that has less than 50,000 max input tokens"
            )
        processing_start_time = time.monotonic()
        language_section = build_language_section(user_language)
        allowed_tools = [
            tool
            for tool in tools
            if tool.name in {SearchTool.NAME, WebSearchTool.NAME, OpenURLTool.NAME}
        ]
        has_internal_search = any(
            tool.name == SearchTool.NAME for tool in allowed_tools
        )
        is_reasoning_model = model_is_reasoning_model(
            llm.config.model_name, llm.config.model_provider
        )
        maximum = (
            MAX_ORCHESTRATOR_CYCLES_REASONING
            if is_reasoning_model
            else MAX_ORCHESTRATOR_CYCLES
        )
        initial_history = construct_message_history(
            system_prompt=ChatMessageSimple(
                message="", token_count=0, message_type=MessageType.SYSTEM
            ),
            custom_agent_prompt=None,
            simple_chat_history=simple_chat_history,
            reminder_message=None,
            context_files=None,
            available_tokens=llm.config.max_input_tokens,
            last_n_user_messages=MAX_USER_MESSAGES_FOR_CONTEXT,
            all_injected_file_metadata=all_injected_file_metadata,
            available_tool_names=set(),
        )
        from onyx.chat.history_translation import translate_history_to_native_messages

        native_history = translate_history_to_native_messages(
            initial_history, llm.config
        )
        research_plan, planning = _plan_research(
            llm=llm,
            emitter=emitter,
            state_container=state_container,
            native_history=native_history,
            token_counter=token_counter,
            reasoning_effort=reasoning_effort,
            user_identity=user_identity,
            language_section=language_section,
            has_internal_search=has_internal_search,
            skip_clarification=SKIP_DEEP_RESEARCH_CLARIFICATION or skip_clarification,
        )
        if not planning:
            state_container.set_is_clarification(True)
            emitter.report(
                placement=Placement(turn_index=0), obj=OverallStop(type="stop")
            )
            return

        cycle = 0
        result_lock = Lock()
        completed_response = False
        report_requested = False
        calls: list[ToolCallKickoff] = []
        reasoning: str | None = None
        citation_mapping: CitationMapping = {}
        citation_processor = DynamicCitationProcessor()
        definitions = get_orchestrator_tools(include_think_tool=not is_reasoning_model)

        def placement() -> Placement:
            return Placement(turn_index=cycle + 1)

        def prepare_step(messages: list[ModelMessage]) -> NativeAgentRequest:
            nonlocal report_requested, cycle, completed_response
            if completed_response:
                cycle += 1
                completed_response = False
            report_requested = (
                report_requested
                or cycle >= maximum - 1
                or time.monotonic() - processing_start_time
                >= DEEP_RESEARCH_FORCE_REPORT_SECONDS
            )
            template = (
                ORCHESTRATOR_PROMPT_REASONING
                if is_reasoning_model
                else ORCHESTRATOR_PROMPT
            )
            prompt = (
                with_language_section(
                    FINAL_REPORT_PROMPT.format(
                        current_datetime=get_current_llm_day_time(full_sentence=False)
                    ),
                    language_section,
                )
                if report_requested
                else template.format(
                    current_datetime=get_current_llm_day_time(full_sentence=False),
                    current_cycle_count=cycle,
                    max_cycles=maximum,
                    research_plan=research_plan,
                    internal_search_research_task_guidance=INTERNAL_SEARCH_RESEARCH_TASK_GUIDANCE
                    if has_internal_search
                    else "",
                )
            )
            history = replace_system(messages, prompt)
            if report_requested:
                history.append(
                    ModelRequest(
                        parts=[
                            UserPromptPart(
                                USER_FINAL_REPORT_QUERY.format(
                                    research_plan=research_plan
                                )
                            )
                        ]
                    )
                )
                state_container.set_pre_answer_processing_time(
                    time.monotonic() - processing_start_time
                )
            elif cycle == 1:
                history.append(
                    ModelRequest(parts=[UserPromptPart(FIRST_CYCLE_REMINDER)])
                )
            return NativeAgentRequest(
                messages=history,
                settings=llm.model_settings(
                    reasoning_effort=reasoning_effort,
                    user_identity=user_identity,
                    max_tokens=MAX_FINAL_REPORT_TOKENS if report_requested else 1024,
                    timeout_override=DR_REPORT_LLM_TIMEOUT_S
                    if report_requested
                    else None,
                    tool_choice=ToolChoiceOptions.NONE
                    if report_requested
                    else ToolChoiceOptions.REQUIRED,
                ),
                tools=[] if report_requested else native_definitions(definitions),
            )

        def finalize_step(response: ModelResponse) -> None:
            nonlocal calls, reasoning, completed_response
            completed_response = True
            calls = [
                ToolCallKickoff(
                    tool_call_id=part.tool_call_id,
                    tool_name=part.tool_name,
                    tool_args=part.args_as_dict(),
                    placement=Placement(turn_index=cycle + 1, tab_index=index),
                )
                for index, part in enumerate(
                    part for part in response.parts if isinstance(part, ToolCallPart)
                )
            ]
            branch_count = sum(
                call.tool_name == RESEARCH_AGENT_TOOL_NAME for call in calls
            )
            if branch_count > 1:
                emitter.report(
                    placement=placement(),
                    obj=TopLevelBranching(num_parallel_branches=branch_count),
                )
            reasoning = (
                "".join(
                    part.content
                    for part in response.parts
                    if isinstance(part, ThinkingPart)
                )
                or None
            )

        async def execute_tool(
            context: RunContext[None], native_call: ToolCallPart
        ) -> str:
            nonlocal report_requested, citation_mapping
            results: dict[str, str] = {}
            research_calls: list[ToolCallKickoff] = []
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
                if call.tool_name == GENERATE_REPORT_TOOL_NAME:
                    report_requested = True
                    results[call.tool_call_id] = "Generate the final report."
                elif call.tool_name == THINK_TOOL_NAME:
                    results[call.tool_call_id] = THINK_TOOL_RESPONSE_MESSAGE
                else:
                    research_calls.append(call)
            if research_calls:
                call = research_calls[0]
                research = await run_research_agent_call(
                    parent_context=context,
                    research_agent_call=call,
                    parent_tool_call_id=call.tool_call_id,
                    tools=allowed_tools,
                    emitter=emitter,
                    state_container=state_container,
                    llm=llm,
                    is_reasoning_model=is_reasoning_model,
                    token_counter=token_counter,
                    language_section=language_section,
                    user_identity=user_identity,
                    reasoning_effort=reasoning_effort
                    if reasoning_effort is not ReasoningEffort.AUTO
                    else ReasoningEffort.LOW,
                )
                check_tool_run_active()
                report = None
                if research is not None:
                    with result_lock:
                        check_tool_run_active()
                        report, citation_mapping = collapse_citations(
                            answer_text=research.intermediate_report,
                            existing_citation_mapping=citation_mapping,
                            new_citation_mapping=research.citation_mapping,
                        )
                        citation_processor.update_citation_mapping(citation_mapping)
                tool_id = await asyncio.to_thread(_get_research_agent_tool_id)
                results[call.tool_call_id] = (
                    report or "Research agent failed. Try another approach."
                )
                state_container.add_tool_call(
                    ToolCallInfo(
                        parent_tool_call_id=None,
                        turn_index=cycle + 1,
                        tab_index=call.placement.tab_index,
                        tool_name=call.tool_name,
                        tool_call_id=call.tool_call_id,
                        tool_id=tool_id,
                        reasoning_tokens=reasoning,
                        tool_call_arguments=call.tool_args,
                        tool_call_response=results[call.tool_call_id],
                        search_docs=None,
                        generated_images=None,
                    )
                )
            return results.get(
                native_call.tool_call_id, "Tool execution produced no result."
            )

        run_native_agent(
            agent_name="research_orchestrator",
            llm=llm,
            prepare_step=prepare_step,
            finalize_step=finalize_step,
            execute_tool_async=execute_tool,
            tool_definitions=definitions,
            max_requests=maximum + 2,
            event_phase=lambda: "report" if report_requested else "research",
            tokenizer=token_counter,
            citation_processor=citation_processor,
            emitter=emitter,
            state_container=state_container,
            placement=placement,
            message_history=native_history,
        )
        state_container.set_citation_mapping(citation_processor.citation_to_doc)
        emitter.report(placement=placement(), obj=OverallStop(type="stop"))
