import time
from collections.abc import Callable, Mapping
from functools import partial

from pydantic import JsonValue

from onyx.agents.models import (
    AgentState,
    PreparedStep,
    RunHooks,
    StepInput,
    StepResult,
)
from onyx.agents.runtime import Agent, AgentFeature
from onyx.agents.tools import AgentTool
from onyx.chat.citation_processor import CitationMapping, DynamicCitationProcessor
from onyx.chat.citation_utils import (
    message_citation_sources,
    remap_received_citations,
)
from onyx.chat.models import CitationMode, PromptMetadata
from onyx.chat.prompt_utils import (
    SearchPassageCache,
    prepare_prompt,
    with_language_section,
)
from onyx.configs.chat_configs import DR_REPORT_LLM_TIMEOUT_S
from onyx.context.search.models import SearchDocsResponse
from onyx.deep_research.models import (
    ResearchConfiguration,
    ResearchFeatureState,
    ResearchMessageMetadata,
    ResearchPhase,
    new_sources,
)
from onyx.deep_research.tool_definitions import (
    GENERATE_REPORT_TOOL_DESCRIPTION,
    GENERATE_REPORT_TOOL_NAME,
)
from onyx.llm.interfaces import LLM, GenerationContext, LLMUserIdentity
from onyx.llm.models import (
    GenerationOptions,
    ReasoningEffort,
    SystemMessage,
    ToolChoiceOptions,
    ToolResult,
    ToolResultMessage,
    UserMessage,
)
from onyx.prompts.deep_research.dr_tool_prompts import (
    INTERNAL_SEARCH_TOOL_DESCRIPTION,
    OPEN_URLS_TOOL_DESCRIPTION,
    WEB_SEARCH_TOOL_DESCRIPTION,
)
from onyx.prompts.deep_research.research_agent import (
    OPEN_URL_REMINDER_RESEARCH_AGENT,
    RESEARCH_AGENT_PROMPT,
    RESEARCH_REPORT_PROMPT,
    USER_REPORT_QUERY,
)
from onyx.prompts.prompt_utils import get_current_llm_day_time
from onyx.tools.interface import Tool
from onyx.tools.models import ToolContext
from onyx.tools.tool_implementations.open_url.open_url_tool import (
    OPEN_URL_TOOL_NAMES,
    OpenURLTool,
)
from onyx.tools.tool_implementations.search.models import SearchContext
from onyx.tools.tool_implementations.search.search_tool import (
    SearchTool,
    update_search_context,
)
from onyx.tools.tool_implementations.skills.skill_tools import (
    SKILL_TOOL_NAMES,
    skills_catalog_message,
)
from onyx.tools.tool_implementations.web_search.utils import extract_url_snippet_map
from onyx.tools.tool_implementations.web_search.web_search_tool import WebSearchTool
from onyx.tools.utils import generate_tools_description
from onyx.tracing.flows import LLMFlow

MAX_INTERMEDIATE_REPORT_LENGTH_TOKENS = 10000
RESEARCH_STEP_OUTPUT_TOKENS = 1000
RESEARCH_AGENT_FORCE_REPORT_SECONDS = 12 * 60


class ResearchFeature(AgentFeature):
    """Investigate one question and return a report with source references:
    an AgentFeature. `agent` builds the agent that runs it."""

    def __init__(
        self,
        tools: list[Tool],
        llm: LLM,
        token_counter: Callable[[str], int],
        user_identity: LLMUserIdentity | None,
        language_section: str,
        reasoning_effort: ReasoningEffort,
        *,
        sources: CitationMapping | None = None,
    ) -> None:
        self.llm = llm
        self.user_identity = user_identity
        allowed_tools = {
            SearchTool.NAME,
            WebSearchTool.NAME,
            *OPEN_URL_TOOL_NAMES,
            *SKILL_TOOL_NAMES,
        }
        self.application_tools = [tool for tool in tools if tool.name in allowed_tools]
        self.skills_catalog_message = skills_catalog_message(
            self.application_tools, llm.config.max_input_tokens
        )
        self.search_context = SearchContext()
        self.started = time.monotonic()
        self.token_counter = token_counter
        self.language_section = language_section
        self.reasoning_effort = reasoning_effort
        # Preserve citation markers in intermediate reports so the parent can
        # renumber them when it combines reports from multiple research agents.
        # Each step's deduplicated search results, for later requests.
        self.search_passage_cache: SearchPassageCache = {}
        self.citation_processor = DynamicCitationProcessor(
            citation_mode=CitationMode.KEEP_MARKERS
        )
        if sources:
            self.citation_processor.update_citation_mapping(sources)
        self.citation_mapping = {
            number: document.document_id for number, document in (sources or {}).items()
        }

    def agent(
        self,
        state: AgentState | None = None,
        *,
        agent_id: str | None = None,
        previous_run_id: str | None = None,
    ) -> Agent:
        """The agent that runs this feature with the same model."""
        return Agent(
            self.llm,
            feature=self,
            state=state,
            agent_id=agent_id,
            previous_run_id=previous_run_id,
            generation_context=GenerationContext(
                flow=LLMFlow.RESEARCH_AGENT, user_identity=self.user_identity
            ),
        )

    def bind(self) -> RunHooks:
        return RunHooks(
            tools=(
                *(
                    tool.bind(self._tool_context, summary_only=True)
                    for tool in self.application_tools
                ),
                AgentTool(
                    definition=GENERATE_REPORT_TOOL_DESCRIPTION,
                    execute=lambda _invocation: ToolResult(
                        content="Ready to produce the research report."
                    ),
                ),
            ),
            prepare_step=self._prepare_step,
            after_step=self._after_step,
            capture_state=self.capture_state,
        )

    def capture_state(self) -> ResearchFeatureState:
        return ResearchFeatureState(
            elapsed_seconds=max(0.0, time.monotonic() - self.started),
            configuration=ResearchConfiguration(
                language_section=self.language_section,
                reasoning_effort=self.reasoning_effort,
            ),
            citation_sources=self.citation_processor.citation_to_doc,
            citation_mapping=self.citation_mapping,
            search_context=self.search_context,
        )

    def restore_state(self, state: Mapping[str, JsonValue]) -> None:
        saved = ResearchFeatureState.model_validate(state)
        self.started = time.monotonic() - saved.elapsed_seconds
        self.search_context = saved.search_context
        self.citation_processor.citation_to_doc = saved.citation_sources
        self.citation_mapping = saved.citation_mapping

    def _tool_context(self) -> ToolContext:
        """Read feature state that advances only after a completed step."""
        return ToolContext(
            search_context=self.search_context,
            citation_mapping=dict(self.citation_mapping),
            next_citation_num=self.citation_processor.get_next_citation_number(),
            url_snippet_map=extract_url_snippet_map(
                list(self.citation_processor.citation_to_doc.values())
            ),
        )

    def _prepare_step(self, state: StepInput) -> PreparedStep:
        previous = state.previous
        results = previous.tool_results if previous else []
        if previous is None:
            self.search_context = SearchContext()
            self.started = time.monotonic()
            for message in state.history:
                if isinstance(message, ToolResultMessage):
                    self._update_sources(message)
        step = state.step
        research_topic = "\n\n".join(message.text for message in state.input_messages)
        just_ran_web_search = bool(previous) and any(
            result.tool_name == WebSearchTool.NAME
            and isinstance(result.details, SearchDocsResponse)
            and result.details.search_docs
            for result in results
        )
        options = GenerationOptions()
        is_final_step = (
            step.is_last
            or time.monotonic() - self.started > RESEARCH_AGENT_FORCE_REPORT_SECONDS
        ) or bool(
            previous
            and (
                not previous.message.tool_calls
                or any(
                    result.tool_name == GENERATE_REPORT_TOOL_NAME
                    for result in previous.tool_results
                )
            )
        )
        options.tool_choice = (
            ToolChoiceOptions.NONE if is_final_step else ToolChoiceOptions.REQUIRED
        )
        options.max_tokens = (
            MAX_INTERMEDIATE_REPORT_LENGTH_TOKENS
            if is_final_step
            else RESEARCH_STEP_OUTPUT_TOKENS
        )
        options.reasoning_effort = self.reasoning_effort
        if is_final_step:
            system_prompt = with_language_section(
                RESEARCH_REPORT_PROMPT, self.language_section
            )
            reminder = USER_REPORT_QUERY.format(research_topic=research_topic)
        else:
            tool_names = {tool.name for tool in self.application_tools}
            open_url_tool = next(
                (
                    tool
                    for tool in self.application_tools
                    if isinstance(tool, OpenURLTool)
                ),
                None,
            )
            system_prompt = RESEARCH_AGENT_PROMPT.format(
                available_tools=generate_tools_description(self.application_tools),
                current_datetime=get_current_llm_day_time(full_sentence=False),
                current_cycle_count=step.index,
                optional_internal_search_tool_description=INTERNAL_SEARCH_TOOL_DESCRIPTION
                if SearchTool.NAME in tool_names
                else "",
                optional_web_search_tool_description=WEB_SEARCH_TOOL_DESCRIPTION
                if WebSearchTool.NAME in tool_names
                else "",
                optional_open_url_tool_description=""
                if open_url_tool is None
                else OPEN_URLS_TOOL_DESCRIPTION.format(name=open_url_tool.name),
            )
            reminder = (
                OPEN_URL_REMINDER_RESEARCH_AGENT.format(name=open_url_tool.name)
                if just_ran_web_search and open_url_tool is not None
                else None
            )
        received = remap_received_citations(
            state.received_inputs, self.citation_processor.citation_to_doc
        )
        self.citation_processor.update_citation_mapping(received.new_citations)
        self.citation_mapping.update(
            {
                number: document.document_id
                for number, document in received.new_citations.items()
            }
        )
        output_metadata = ResearchMessageMetadata(
            phase=ResearchPhase.REPORT if is_final_step else ResearchPhase.RESEARCH,
            is_intermediate=True,
            # The parent reads the report step's sources alone.
            sources=dict(self.citation_processor.citation_to_doc)
            if is_final_step
            else new_sources(self.citation_processor.citation_to_doc, state.messages),
        )
        return PreparedStep(
            input_messages=received.messages,
            allowed_tool_names=frozenset() if is_final_step else None,
            options=options,
            stall_timeout_s=DR_REPORT_LLM_TIMEOUT_S if is_final_step else None,
            output_metadata=output_metadata,
            assemble_messages=partial(
                prepare_prompt,
                search_passage_cache=self.search_passage_cache,
                system_prompt=SystemMessage(content=system_prompt),
                skills_catalog_message=self.skills_catalog_message,
                custom_agent_prompt=None,
                reminder_message=UserMessage(
                    content=reminder, metadata=PromptMetadata(is_reminder=True)
                )
                if reminder
                else None,
                context_files=None,
                token_counter=self.token_counter,
                llm_config=self.llm.config,
            ),
        )

    def _after_step(self, result: StepResult) -> bool:
        self.search_context = update_search_context(
            self.search_context, result.tool_results
        )
        for tool_result in result.tool_results:
            self._update_sources(tool_result)
        # Research steps continue; the runtime ends the report step.
        return True

    def _update_sources(self, result: ToolResultMessage) -> None:
        if isinstance(result.details, SearchDocsResponse):
            self.citation_mapping.update(result.details.citation_mapping)
            self.citation_processor.update_citation_mapping(
                message_citation_sources(result)
            )
