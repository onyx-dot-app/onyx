from collections.abc import Callable
from functools import partial

from pydantic import BaseModel

from onyx.agents.models import (
    AgentContext,
    PreparedStep,
    RunResult,
    StepInput,
    StepResult,
)
from onyx.agents.runtime import Agent
from onyx.agents.tools import AgentTool
from onyx.agents.transcript import CompactionCheckpoint
from onyx.chat.citation_processor import (
    CitationMapping,
    CitationMode,
    DynamicCitationProcessor,
)
from onyx.chat.citation_utils import (
    extract_citation_order_from_text,
    update_citation_processor_from_tool_result,
)
from onyx.chat.prompt_utils import with_language_section
from onyx.configs.chat_configs import DR_REPORT_LLM_TIMEOUT_S
from onyx.context.messages import PromptMetadata
from onyx.context.prompt import prepare_prompt
from onyx.context.search.models import SearchDocsResponse
from onyx.deep_research.models import (
    ResearchAgentCallResult,
    ResearchPhase,
    ResearchStepOutput,
)
from onyx.deep_research.tool_definitions import (
    GENERATE_REPORT_TOOL_NAME,
    THINK_TOOL_RESPONSE_MESSAGE,
    get_research_agent_additional_tool_definitions,
)
from onyx.llm.interfaces import LLM, GenerationContext, LLMUserIdentity
from onyx.llm.model_capabilities import model_is_reasoning_model
from onyx.llm.models import (
    GenerationOptions,
    Message,
    ReasoningEffort,
    SystemMessage,
    ToolChoiceOptions,
    ToolResult,
    ToolResultMessage,
    UserMessage,
)
from onyx.prompts.deep_research.dr_tool_prompts import (
    OPEN_URLS_TOOL_DESCRIPTION,
    OPEN_URLS_TOOL_DESCRIPTION_REASONING,
    WEB_SEARCH_TOOL_DESCRIPTION,
)
from onyx.prompts.deep_research.research_agent import (
    OPEN_URL_REMINDER_RESEARCH_AGENT,
    RESEARCH_AGENT_PROMPT,
    RESEARCH_AGENT_PROMPT_REASONING,
    RESEARCH_REPORT_PROMPT,
    USER_REPORT_QUERY,
)
from onyx.prompts.prompt_utils import get_current_llm_day_time
from onyx.prompts.tool_prompts import INTERNAL_SEARCH_GUIDANCE
from onyx.tools.interface import Tool, ToolContext
from onyx.tools.tool_implementations.open_url.open_url_tool import OpenURLTool
from onyx.tools.tool_implementations.search.search_tool import SearchTool
from onyx.tools.tool_implementations.web_search.utils import extract_url_snippet_map
from onyx.tools.tool_implementations.web_search.web_search_tool import WebSearchTool
from onyx.tools.tool_runner import bind_tool
from onyx.tools.utils import generate_tools_description
from onyx.tracing.flows import LLMFlow

MAX_INTERMEDIATE_REPORT_LENGTH_TOKENS = 10000
RESEARCH_STEP_OUTPUT_TOKENS = 1000


class ResearchConfiguration(BaseModel):
    language_section: str
    reasoning_effort: ReasoningEffort


class ResearchAgent:
    """Investigate one question and return a report with source references."""

    def __init__(
        self,
        tools: list[Tool],
        llm: LLM,
        token_counter: Callable[[str], int],
        user_identity: LLMUserIdentity | None,
        language_section: str,
        reasoning_effort: ReasoningEffort,
        *,
        messages: list[Message] | None = None,
        checkpoint: CompactionCheckpoint | None = None,
        sources: CitationMapping | None = None,
        previous_run_id: str | None = None,
    ) -> None:
        allowed_names = {SearchTool.NAME, WebSearchTool.NAME, OpenURLTool.NAME}
        self.tools = [tool.for_agent() for tool in tools if tool.name in allowed_names]
        self.llm = llm
        self.is_reasoning_model = model_is_reasoning_model(
            llm.info.model_name, llm.info.model_provider
        )
        self.token_counter = token_counter
        self.language_section = language_section
        self.reasoning_effort = reasoning_effort
        self.citation_processor = DynamicCitationProcessor(
            citation_mode=CitationMode.KEEP_MARKERS
        )
        if sources:
            self.citation_processor.update_citation_mapping(sources)
        self.citation_mapping = {
            number: document.document_id for number, document in (sources or {}).items()
        }
        self.agent = Agent(
            llm,
            previous_run_id=previous_run_id,
            context=AgentContext(
                messages=messages or [],
                checkpoint=checkpoint,
            ),
            prepare_step=self.prepare_step,
            after_step=self.after_step,
            execution=GenerationContext(
                flow=LLMFlow.RESEARCH_AGENT, user_identity=user_identity
            ),
        )

    def prepare_step(self, state: StepInput) -> PreparedStep:
        previous = state.previous
        results = previous.tool_results if previous else []
        if previous is None:
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
        is_final_step = step.is_last or bool(
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
        tools = []
        if is_final_step:
            system_prompt = with_language_section(
                RESEARCH_REPORT_PROMPT, self.language_section
            )
            reminder = USER_REPORT_QUERY.format(research_topic=research_topic)
        else:
            tool_context = ToolContext(
                citation_mapping=dict(self.citation_mapping),
                next_citation_num=self.citation_processor.get_next_citation_number(),
                url_snippet_map=extract_url_snippet_map(
                    list(self.citation_processor.citation_to_doc.values())
                ),
            )
            tools = [bind_tool(tool, tool_context) for tool in self.tools]
            for definition in get_research_agent_additional_tool_definitions(
                not self.is_reasoning_model
            ):
                function = definition["function"]
                tools.append(
                    AgentTool(
                        name=function["name"],
                        description=function["description"],
                        parameters=function["parameters"],
                        execute=lambda _invocation, name=function["name"]: ToolResult(
                            content="Ready to produce the research report."
                            if name == GENERATE_REPORT_TOOL_NAME
                            else THINK_TOOL_RESPONSE_MESSAGE
                        ),
                    )
                )
            tool_names = {tool.name for tool in self.tools}
            has_open_url = OpenURLTool.NAME in tool_names
            template = (
                RESEARCH_AGENT_PROMPT_REASONING
                if self.is_reasoning_model
                else RESEARCH_AGENT_PROMPT
            )
            system_prompt = template.format(
                available_tools=generate_tools_description(self.tools),
                current_datetime=get_current_llm_day_time(full_sentence=False),
                current_cycle_count=step.index,
                optional_internal_search_tool_description=INTERNAL_SEARCH_GUIDANCE
                if SearchTool.NAME in tool_names
                else "",
                optional_web_search_tool_description=WEB_SEARCH_TOOL_DESCRIPTION
                if WebSearchTool.NAME in tool_names
                else "",
                optional_open_url_tool_description=(
                    OPEN_URLS_TOOL_DESCRIPTION_REASONING
                    if self.is_reasoning_model
                    else OPEN_URLS_TOOL_DESCRIPTION
                )
                if has_open_url
                else "",
            )
            reminder = (
                OPEN_URL_REMINDER_RESEARCH_AGENT
                if just_ran_web_search and has_open_url
                else None
            )
        output_metadata = ResearchStepOutput(
            phase=ResearchPhase.REPORT if is_final_step else ResearchPhase.RESEARCH,
            is_intermediate=True,
            is_reasoning_model=self.is_reasoning_model,
            sources=dict(self.citation_processor.citation_to_doc),
        )
        return PreparedStep(
            tools=tools,
            options=options,
            timeout=DR_REPORT_LLM_TIMEOUT_S if is_final_step else None,
            output_metadata=output_metadata,
            assemble_messages=partial(
                prepare_prompt,
                system_prompt=SystemMessage(content=system_prompt),
                custom_agent_prompt=None,
                reminder_message=UserMessage(
                    content=reminder, metadata=PromptMetadata(is_reminder=True)
                )
                if reminder
                else None,
                context_files=None,
                token_counter=self.token_counter,
                llm_info=self.llm.info,
            ),
        )

    def after_step(self, result: StepResult) -> bool:
        for tool_result in result.tool_results:
            self._update_sources(tool_result)
        if result.request.options.tool_choice != ToolChoiceOptions.NONE:
            return True
        if not result.message.text:
            raise ValueError("Model failed to produce a research report")
        return False

    def _update_sources(self, result: ToolResultMessage) -> None:
        if isinstance(result.details, SearchDocsResponse):
            self.citation_mapping.update(result.details.citation_mapping)
            update_citation_processor_from_tool_result(result, self.citation_processor)

    def report(self, completed: RunResult) -> ResearchAgentCallResult:
        report = completed.output.text
        if not report:
            raise ValueError("Model failed to produce a research report")
        return ResearchAgentCallResult(
            intermediate_report=report,
            citation_mapping={
                number: self.citation_processor.citation_to_doc[number]
                for number in extract_citation_order_from_text(report)
                if number in self.citation_processor.citation_to_doc
            },
        )
