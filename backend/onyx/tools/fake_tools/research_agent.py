import queue
from collections.abc import Callable
from typing import Any
from typing import cast

from onyx.chat.chat_state import ChatStateContainer
from onyx.chat.chat_utils import create_tool_call_failure_messages
from onyx.chat.citation_processor import CitationMapping
from onyx.chat.citation_processor import CitationMode
from onyx.chat.citation_processor import DynamicCitationProcessor
from onyx.chat.citation_utils import collapse_citations
from onyx.chat.citation_utils import update_citation_processor_from_tool_response
from onyx.chat.emitter import Emitter
from onyx.chat.llm_loop import construct_message_history
from onyx.chat.llm_step import run_llm_step_pkt_generator
from onyx.chat.models import ChatMessageSimple
from onyx.chat.models import LlmStepResult
from onyx.configs.constants import MessageType
from onyx.context.search.models import SearchDocsResponse
from onyx.deep_research.dr_mock_tools import GENERATE_REPORT_TOOL_NAME
from onyx.deep_research.dr_mock_tools import (
    get_research_agent_additional_tool_definitions,
)
from onyx.deep_research.dr_mock_tools import RESEARCH_AGENT_TASK_KEY
from onyx.deep_research.models import CombinedResearchAgentCallResult
from onyx.deep_research.models import ResearchAgentCallResult
from onyx.llm.interfaces import LLM
from onyx.llm.interfaces import LLMUserIdentity
from onyx.llm.models import ReasoningEffort
from onyx.llm.models import ToolChoiceOptions
from onyx.prompts.deep_research.dr_tool_prompts import OPEN_URLS_TOOL_DESCRIPTION
from onyx.prompts.deep_research.dr_tool_prompts import (
    OPEN_URLS_TOOL_DESCRIPTION_REASONING,
)
from onyx.prompts.deep_research.dr_tool_prompts import WEB_SEARCH_TOOL_DESCRIPTION
from onyx.prompts.deep_research.research_agent import MAX_RESEARCH_CYCLES
from onyx.prompts.deep_research.research_agent import OPEN_URL_REMINDER_RESEARCH_AGENT
from onyx.prompts.deep_research.research_agent import RESEARCH_AGENT_PROMPT
from onyx.prompts.deep_research.research_agent import RESEARCH_AGENT_PROMPT_REASONING
from onyx.prompts.deep_research.research_agent import RESEARCH_REPORT_PROMPT
from onyx.prompts.deep_research.research_agent import USER_REPORT_QUERY
from onyx.prompts.prompt_utils import get_current_llm_day_time
from onyx.prompts.tool_prompts import INTERNAL_SEARCH_GUIDANCE
from onyx.server.query_and_chat.placement import Placement
from onyx.server.query_and_chat.streaming_models import AgentResponseDelta
from onyx.server.query_and_chat.streaming_models import AgentResponseStart
from onyx.server.query_and_chat.streaming_models import IntermediateReportCitedDocs
from onyx.server.query_and_chat.streaming_models import IntermediateReportDelta
from onyx.server.query_and_chat.streaming_models import IntermediateReportStart
from onyx.server.query_and_chat.streaming_models import Packet
from onyx.server.query_and_chat.streaming_models import ResearchAgentStart
from onyx.server.query_and_chat.streaming_models import SectionEnd
from onyx.tools.fake_tools.agent_loop_utils import build_assistant_with_tool_calls
from onyx.tools.fake_tools.agentic_agent_base import AgenticAgentBase
from onyx.tools.interface import Tool
from onyx.tools.models import ToolCallInfo
from onyx.tools.models import ToolCallKickoff
from onyx.tools.tool_implementations.open_url.open_url_tool import OpenURLTool
from onyx.tools.tool_implementations.search.search_tool import SearchTool
from onyx.tools.tool_implementations.web_search.utils import extract_url_snippet_map
from onyx.tools.tool_implementations.web_search.web_search_tool import WebSearchTool
from onyx.tools.tool_runner import run_tool_calls
from onyx.tools.utils import generate_tools_description
from onyx.tracing.framework.create import function_span
from onyx.utils.logger import setup_logger
from onyx.utils.threadpool_concurrency import run_functions_tuples_in_parallel

logger = setup_logger()


# 30 minute timeout per research agent
RESEARCH_AGENT_TIMEOUT_SECONDS = 30 * 60
RESEARCH_AGENT_TIMEOUT_MESSAGE = "Research Agent timed out after 30 minutes"
# 12 minute timeout before forcing intermediate report generation
RESEARCH_AGENT_FORCE_REPORT_SECONDS = 12 * 60
# May be good to experiment with this, empirically reports of around 5,000 tokens are pretty good.
MAX_INTERMEDIATE_REPORT_LENGTH_TOKENS = 10000


def generate_intermediate_report(
    research_topic: str,
    history: list[ChatMessageSimple],
    llm: LLM,
    token_counter: Callable[[str], int],
    citation_processor: DynamicCitationProcessor,
    user_identity: LLMUserIdentity | None,
    emitter: Emitter,
    placement: Placement,
) -> str:
    # NOTE: This step outputs a lot of tokens and has been observed to run for more than 10 minutes in a nontrivial percentage of
    # research tasks. This is also model / inference provider dependent.
    with function_span("generate_intermediate_report") as span:
        span.span_data.input = (
            f"research_topic={research_topic}, history_length={len(history)}"
        )
        # Having the state container here to handle the tokens and not passed through means there is no way to
        # get partial saves of the report. Arguably this is not useful anyway so not going to implement partial saves.
        state_container = ChatStateContainer()
        system_prompt = ChatMessageSimple(
            message=RESEARCH_REPORT_PROMPT,
            token_count=token_counter(RESEARCH_REPORT_PROMPT),
            message_type=MessageType.SYSTEM,
        )

        reminder_str = USER_REPORT_QUERY.format(research_topic=research_topic)
        reminder_message = ChatMessageSimple(
            message=reminder_str,
            token_count=token_counter(reminder_str),
            message_type=MessageType.USER,
        )

        research_history = construct_message_history(
            system_prompt=system_prompt,
            custom_agent_prompt=None,
            simple_chat_history=history,
            reminder_message=reminder_message,
            context_files=None,
            available_tokens=llm.config.max_input_tokens,
        )

        intermediate_report_generator = run_llm_step_pkt_generator(
            history=research_history,
            tool_definitions=[],
            tool_choice=ToolChoiceOptions.NONE,
            llm=llm,
            placement=placement,
            citation_processor=citation_processor,
            state_container=state_container,
            reasoning_effort=ReasoningEffort.LOW,
            final_documents=None,
            user_identity=user_identity,
            max_tokens=MAX_INTERMEDIATE_REPORT_LENGTH_TOKENS,
            use_existing_tab_index=True,
            is_deep_research=True,
            timeout_override=300,  # 5 minute read timeout for long report generation
        )

        while True:
            try:
                packet = next(intermediate_report_generator)
                # Translate AgentResponseStart/Delta packets to IntermediateReportStart/Delta
                # Use original placement consistently for all packets
                if isinstance(packet.obj, AgentResponseStart):
                    emitter.emit(
                        Packet(
                            placement=placement,
                            obj=IntermediateReportStart(),
                        )
                    )
                elif isinstance(packet.obj, AgentResponseDelta):
                    emitter.emit(
                        Packet(
                            placement=placement,
                            obj=IntermediateReportDelta(content=packet.obj.content),
                        )
                    )
                else:
                    # Pass through other packet types (e.g., ReasoningStart, ReasoningDelta, etc.)
                    # Also use original placement to keep everything in the same group
                    emitter.emit(
                        Packet(
                            placement=placement,
                            obj=packet.obj,
                        )
                    )
            except StopIteration as e:
                llm_step_result, _ = e.value
                # Use original placement for completion packets
                emitter.emit(
                    Packet(
                        placement=placement,
                        obj=IntermediateReportCitedDocs(
                            cited_docs=list(
                                citation_processor.get_seen_citations().values()
                            )
                        ),
                    )
                )
                emitter.emit(
                    Packet(
                        placement=placement,
                        obj=SectionEnd(),
                    )
                )
                break

        llm_step_result = cast(LlmStepResult, llm_step_result)

        final_report = llm_step_result.answer
        span.span_data.output = final_report if final_report else None
        if final_report is None:
            raise ValueError(
                f"LLM failed to generate a report for research task: {research_topic}"
            )

        return final_report


class ResearchAgent(AgenticAgentBase[ResearchAgentCallResult]):
    agent_name = "research_agent"
    max_cycles = MAX_RESEARCH_CYCLES
    force_finalize_seconds = RESEARCH_AGENT_FORCE_REPORT_SECONDS
    finalize_tool_name = GENERATE_REPORT_TOOL_NAME
    # In case the model is tripped up by the long context and gets into an
    # endless loop of e.g. null tokens, we cap output. None of the tool calls
    # should be this long.
    max_step_tokens = 1000
    is_deep_research = True

    def __init__(
        self,
        kickoff: ToolCallKickoff,
        emitter: Emitter,
        llm: LLM,
        token_counter: Callable[[str], int],
        user_identity: LLMUserIdentity | None,
        *,
        parent_tool_call_id: str,
        tools: list[Tool],
        state_container: ChatStateContainer,
    ):
        super().__init__(kickoff, emitter, llm, token_counter, user_identity)
        self.parent_tool_call_id = parent_tool_call_id
        self.tools = tools
        self.state_container = state_container
        self.tools_by_name: dict[str, Tool] = {t.name: t for t in tools}
        # If this fails to parse, the loop can't run anyway — let it raise.
        self.research_topic: str = kickoff.tool_args[RESEARCH_AGENT_TASK_KEY]
        # KEEP_MARKERS preserves citation markers like [1], [2] in intermediate
        # reports so collapse_citations() can renumber them in the final report.
        self.citation_processor = DynamicCitationProcessor(
            citation_mode=CitationMode.KEEP_MARKERS
        )
        self.citation_mapping: dict[int, str] = {}
        self.just_ran_web_search = False

    def emit_start(self) -> None:
        self.emitter.emit(
            Packet(
                placement=self.root_placement,
                obj=ResearchAgentStart(research_task=self.research_topic),
            )
        )

    def initial_user_message(self) -> ChatMessageSimple:
        return ChatMessageSimple(
            message=self.research_topic,
            token_count=self.token_counter(self.research_topic),
            message_type=MessageType.USER,
        )

    def render_system_prompt(self, cycle: int) -> str:
        tools_description = generate_tools_description(self.tools)
        internal_search_tip = (
            INTERNAL_SEARCH_GUIDANCE
            if any(isinstance(t, SearchTool) for t in self.tools)
            else ""
        )
        web_search_tip = (
            WEB_SEARCH_TOOL_DESCRIPTION
            if any(isinstance(t, WebSearchTool) for t in self.tools)
            else ""
        )
        open_urls_tip = (
            OPEN_URLS_TOOL_DESCRIPTION
            if any(isinstance(t, OpenURLTool) for t in self.tools)
            else ""
        )
        if self.is_reasoning_model and open_urls_tip:
            open_urls_tip = OPEN_URLS_TOOL_DESCRIPTION_REASONING

        template = (
            RESEARCH_AGENT_PROMPT_REASONING
            if self.is_reasoning_model
            else RESEARCH_AGENT_PROMPT
        )
        return template.format(
            available_tools=tools_description,
            current_datetime=get_current_llm_day_time(full_sentence=False),
            current_cycle_count=cycle,
            optional_internal_search_tool_description=internal_search_tip,
            optional_web_search_tool_description=web_search_tip,
            optional_open_url_tool_description=open_urls_tip,
        )

    def tool_definitions(self) -> list[dict[str, Any]]:
        return [tool.tool_definition() for tool in self.tools] + (
            get_research_agent_additional_tool_definitions(
                include_think_tool=not self.is_reasoning_model
            )
        )

    def reminder_message(self) -> ChatMessageSimple | None:
        if not self.just_ran_web_search:
            return None
        # Consume the flag — the reminder applies once after a web search
        # produced docs.
        self.just_ran_web_search = False
        return ChatMessageSimple(
            message=OPEN_URL_REMINDER_RESEARCH_AGENT,
            token_count=100,
            message_type=MessageType.USER,
        )

    def filter_tool_calls(
        self, tool_calls: list[ToolCallKickoff]
    ) -> list[ToolCallKickoff]:
        # TODO handle the restriction of only 1 tool call type per turn —
        # the Placement system can't differentiate sub-tool calls of mixed
        # types yet, so keep only the first type the model emitted.
        if not tool_calls:
            return tool_calls
        first_type = tool_calls[0].tool_name
        return [tc for tc in tool_calls if tc.tool_name == first_type]

    def execute_tool_calls(
        self,
        tool_calls: list[ToolCallKickoff],
        step_result: LlmStepResult,
        step_placement: Placement,
    ) -> bool:
        parallel_results = run_tool_calls(
            tool_calls=tool_calls,
            tools=self.tools,
            message_history=self.msg_history,
            user_memory_context=None,
            user_info=None,
            citation_mapping=self.citation_mapping,
            next_citation_num=self.citation_processor.get_next_citation_number(),
            # Packets can't differentiate parallel calls at a nested level;
            # deep research doesn't actually emit parallel anyway.
            max_concurrent_tools=1,
            skip_search_query_expansion=False,
            url_snippet_map=extract_url_snippet_map(
                [
                    search_doc
                    for tc in self.state_container.get_tool_calls()
                    if tc.search_docs
                    for search_doc in tc.search_docs
                ]
            ),
        )
        self.citation_mapping = parallel_results.updated_citation_mapping

        if tool_calls and not parallel_results.tool_responses:
            # Tool dispatch failed entirely; record failure messages and
            # continue so we don't infinite-loop on the same prompt.
            failure_messages = create_tool_call_failure_messages(
                tool_calls, self.token_counter
            )
            self.msg_history.extend(failure_messages)
            return True

        valid_tool_responses = [
            tr for tr in parallel_results.tool_responses if tr.tool_call is not None
        ]
        if not valid_tool_responses:
            return True

        # OpenAI parallel-tool-calls form: one assistant message bundling
        # every call, then TOOL_CALL_RESPONSE messages one-per-call.
        valid_tool_calls = [
            tr.tool_call for tr in valid_tool_responses if tr.tool_call is not None
        ]
        self.msg_history.append(
            build_assistant_with_tool_calls(
                tool_calls=valid_tool_calls, token_counter=self.token_counter
            )
        )

        for tool_response in valid_tool_responses:
            tc = tool_response.tool_call
            assert tc is not None  # filtered above
            tool = self.tools_by_name.get(tc.tool_name)
            if not tool:
                raise ValueError(f"Tool '{tc.tool_name}' not found in tools list")

            search_docs = None
            displayed_docs = None
            if isinstance(tool_response.rich_response, SearchDocsResponse):
                search_docs = tool_response.rich_response.search_docs
                displayed_docs = tool_response.rich_response.displayed_docs
                if search_docs:
                    self.state_container.add_search_docs(search_docs)
                # Open-URL reminder fires only when web search yielded docs.
                if search_docs and tc.tool_name == WebSearchTool.NAME:
                    self.just_ran_web_search = True

            update_citation_processor_from_tool_response(
                tool_response=tool_response,
                citation_processor=self.citation_processor,
            )

            # Research Agent is a top-level tool call; tools called by the
            # research agent are sub-tool calls. At DB save time there's
            # only a turn index — sub-turn is implied by the parent's turn
            # and the depth of the tree traversal.
            tool_call_info = ToolCallInfo(
                parent_tool_call_id=self.parent_tool_call_id,
                turn_index=step_placement.sub_turn_index or 0,
                tab_index=tc.placement.tab_index,
                tool_name=tc.tool_name,
                tool_call_id=tc.tool_call_id,
                tool_id=tool.id,
                reasoning_tokens=step_result.reasoning or self.most_recent_reasoning,
                tool_call_arguments=tc.tool_args,
                tool_call_response=tool_response.llm_facing_response,
                search_docs=displayed_docs or search_docs,
                generated_images=None,
            )
            self.state_container.add_tool_call(tool_call_info)

            self.msg_history.append(
                ChatMessageSimple(
                    message=tool_response.llm_facing_response,
                    token_count=self.token_counter(tool_response.llm_facing_response),
                    message_type=MessageType.TOOL_CALL_RESPONSE,
                    tool_call_id=tc.tool_call_id,
                    image_files=None,
                )
            )

        return True

    def finalize(self) -> ResearchAgentCallResult:
        final_report = generate_intermediate_report(
            research_topic=self.research_topic,
            history=self.msg_history,
            llm=self.llm,
            token_counter=self.token_counter,
            citation_processor=self.citation_processor,
            user_identity=self.user_identity,
            emitter=self.emitter,
            placement=self.root_placement,
        )
        return ResearchAgentCallResult(
            intermediate_report=final_report,
            citation_mapping=self.citation_processor.get_seen_citations(),
        )


def run_research_agent_call(
    research_agent_call: ToolCallKickoff,
    parent_tool_call_id: str,
    tools: list[Tool],
    emitter: Emitter,
    state_container: ChatStateContainer,
    llm: LLM,
    is_reasoning_model: bool,  # noqa: ARG001 — derived from llm; kept for API stability
    token_counter: Callable[[str], int],
    user_identity: LLMUserIdentity | None,
) -> ResearchAgentCallResult | None:
    return ResearchAgent(
        kickoff=research_agent_call,
        emitter=emitter,
        llm=llm,
        token_counter=token_counter,
        user_identity=user_identity,
        parent_tool_call_id=parent_tool_call_id,
        tools=tools,
        state_container=state_container,
    ).run()


def _on_research_agent_timeout(
    index: int,  # noqa: ARG001
    func: Callable[..., Any],  # noqa: ARG001
    args: tuple[Any, ...],
) -> ResearchAgentCallResult:
    """Callback for handling research agent timeouts.

    Returns a ResearchAgentCallResult with the timeout message so the research
    can continue with other agents.
    """
    research_agent_call: ToolCallKickoff = args[0]  # First arg
    research_task = research_agent_call.tool_args.get(
        RESEARCH_AGENT_TASK_KEY, "unknown"
    )
    logger.warning(
        "Research agent timed out after %s seconds for task: %s",
        RESEARCH_AGENT_TIMEOUT_SECONDS,
        research_task,
    )
    return ResearchAgentCallResult(
        intermediate_report=RESEARCH_AGENT_TIMEOUT_MESSAGE,
        citation_mapping={},
    )


def run_research_agent_calls(
    research_agent_calls: list[ToolCallKickoff],
    parent_tool_call_ids: list[str],
    tools: list[Tool],
    emitter: Emitter,
    state_container: ChatStateContainer,
    llm: LLM,
    is_reasoning_model: bool,
    token_counter: Callable[[str], int],
    citation_mapping: CitationMapping,
    user_identity: LLMUserIdentity | None = None,
) -> CombinedResearchAgentCallResult:
    # Run all research agent calls in parallel with timeout
    functions_with_args = [
        (
            run_research_agent_call,
            (
                research_agent_call,
                parent_tool_call_id,
                tools,
                emitter,
                state_container,
                llm,
                is_reasoning_model,
                token_counter,
                user_identity,
            ),
        )
        for research_agent_call, parent_tool_call_id in zip(
            research_agent_calls, parent_tool_call_ids
        )
    ]

    research_agent_call_results = run_functions_tuples_in_parallel(
        functions_with_args,
        allow_failures=False,
        # Note: This simply allows the main thread to continue with an error message
        # It does not kill the background thread which may still write to the state objects passed to it
        # This is because forcefully killing Python threads is very dangerous
        timeout=RESEARCH_AGENT_TIMEOUT_SECONDS,
        timeout_callback=_on_research_agent_timeout,
    )

    updated_citation_mapping = citation_mapping
    updated_answers: list[str | None] = []

    for result in research_agent_call_results:
        if result is None:
            updated_answers.append(None)
            continue

        # Use collapse_citations to renumber citations in the text and merge mappings.
        # Since we use KEEP_MARKERS mode, the intermediate reports have original citation
        # markers like [1], [2] which need to be renumbered for the combined report.
        updated_answer, updated_citation_mapping = collapse_citations(
            answer_text=result.intermediate_report,
            existing_citation_mapping=updated_citation_mapping,
            new_citation_mapping=result.citation_mapping,
        )
        updated_answers.append(updated_answer)

    return CombinedResearchAgentCallResult(
        intermediate_reports=updated_answers,
        citation_mapping=updated_citation_mapping,
    )


if __name__ == "__main__":
    from uuid import uuid4

    from onyx.chat.chat_state import ChatStateContainer
    from onyx.db.engine.sql_engine import get_session_with_current_tenant
    from onyx.db.engine.sql_engine import SqlEngine
    from onyx.db.models import User
    from onyx.db.persona import get_default_behavior_persona
    from onyx.llm.factory import get_default_llm
    from onyx.llm.factory import get_llm_token_counter
    from onyx.llm.utils import model_is_reasoning_model
    from onyx.server.query_and_chat.placement import Placement
    from onyx.tools.models import ToolCallKickoff
    from onyx.tools.tool_constructor import construct_tools

    # === CONFIGURE YOUR RESEARCH PROMPT HERE ===
    RESEARCH_PROMPT = "Your test research task."

    SqlEngine.set_app_name("research_agent_script")
    SqlEngine.init_engine(pool_size=5, max_overflow=5)

    with get_session_with_current_tenant() as db_session:
        llm = get_default_llm()
        token_counter = get_llm_token_counter(llm)
        is_reasoning = model_is_reasoning_model(
            llm.config.model_name, llm.config.model_provider
        )

        persona = get_default_behavior_persona(db_session, eager_load_for_tools=True)
        if persona is None:
            raise ValueError("No default persona found")

        user = db_session.query(User).first()
        if user is None:
            raise ValueError("No users found in database. Please create a user first.")

        emitter_queue: queue.Queue = queue.Queue()
        emitter = Emitter(merged_queue=emitter_queue)
        state_container = ChatStateContainer()

        tool_dict = construct_tools(
            persona=persona,
            db_session=db_session,
            emitter=emitter,
            user=user,
            llm=llm,
        )
        tools = [
            tool
            for tool_list in tool_dict.values()
            for tool in tool_list
            if tool.name != "generate_image"
        ]

        logger.info("Running research agent with prompt: %s", RESEARCH_PROMPT)
        logger.info("LLM: %s/%s", llm.config.model_provider, llm.config.model_name)
        logger.info("Tools: %s", [t.name for t in tools])

        result = run_research_agent_call(
            research_agent_call=ToolCallKickoff(
                tool_name="research_agent",
                tool_args={RESEARCH_AGENT_TASK_KEY: RESEARCH_PROMPT},
                tool_call_id=str(uuid4()),
                placement=Placement(turn_index=0, tab_index=0),
            ),
            parent_tool_call_id=str(uuid4()),
            tools=tools,
            emitter=emitter,
            state_container=state_container,
            llm=llm,
            is_reasoning_model=is_reasoning,
            token_counter=token_counter,
            user_identity=None,
        )

        if result is None:
            logger.error("Research agent returned no result")
        else:
            print("\n" + "=" * 80)
            print("RESEARCH AGENT RESULT")
            print("=" * 80)
            print(result.intermediate_report)
            print("=" * 80)
            print(f"Citations: {result.citation_mapping}")
            print(f"Total packets emitted: {emitter_queue.qsize()}")
