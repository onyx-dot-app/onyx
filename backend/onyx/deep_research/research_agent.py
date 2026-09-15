from collections.abc import Callable

from onyx.agents.runtime import (
    Agent,
    AgentContext,
    AgentHooks,
    AgentStep,
    RunResult,
    StepResult,
)
from onyx.agents.tools import AgentTool
from onyx.chat.citation_processor import CitationMode, DynamicCitationProcessor
from onyx.chat.citation_utils import (
    extract_citation_order_from_text,
    update_citation_processor_from_tool_result,
)
from onyx.chat.prompt_utils import with_language_section
from onyx.configs.chat_configs import DR_REPORT_LLM_TIMEOUT_S
from onyx.context.messages import PromptMetadata, prepare_model_messages
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
from onyx.llm.models import (
    GenerationRequest,
    Message,
    ReasoningEffort,
    SystemMessage,
    ToolChoiceOptions,
    ToolResult,
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


class ResearchAgent:
    """Investigate one question and return a report with source references."""

    def __init__(
        self,
        research_topic: str,
        tools: list[Tool],
        llm: LLM,
        is_reasoning_model: bool,
        token_counter: Callable[[str], int],
        user_identity: LLMUserIdentity | None,
        language_section: str,
        reasoning_effort: ReasoningEffort,
    ) -> None:
        self.research_topic = research_topic
        self.tools = tools
        self.llm = llm
        self.is_reasoning_model = is_reasoning_model
        self.token_counter = token_counter
        self.user_identity = user_identity
        self.language_section = language_section
        self.reasoning_effort = reasoning_effort
        self.citation_processor = DynamicCitationProcessor(
            citation_mode=CitationMode.KEEP_MARKERS
        )
        self.citation_mapping: dict[int, str] = {}
        self.just_ran_web_search = False
        self.requested_final = False
        self.is_final_step = False
        self.system_prompt = ""
        self.reminder: str | None = None
        self.agent = Agent(
            llm,
            context=AgentContext(
                execution=GenerationContext(flow=LLMFlow.RESEARCH_AGENT),
            ),
            hooks=AgentHooks(
                prepare_step=self._prepare_step,
                build_request=self._build_request,
                after_step=self._after_step,
            ),
        )

    @property
    def input_messages(self) -> list[Message]:
        return [UserMessage(content=self.research_topic)]

    def _prepare_step(self, context: AgentContext, step: AgentStep) -> AgentContext:
        self.is_final_step = self.requested_final or step.is_last
        context.options.tool_choice = (
            ToolChoiceOptions.NONE if self.is_final_step else ToolChoiceOptions.REQUIRED
        )
        context.options.max_tokens = (
            MAX_INTERMEDIATE_REPORT_LENGTH_TOKENS
            if self.is_final_step
            else RESEARCH_STEP_OUTPUT_TOKENS
        )
        context.options.reasoning_effort = self.reasoning_effort
        context.execution.timeout = (
            DR_REPORT_LLM_TIMEOUT_S if self.is_final_step else None
        )
        context.execution.user_identity = self.user_identity
        context.tools = []
        if self.is_final_step:
            self.system_prompt = with_language_section(
                RESEARCH_REPORT_PROMPT, self.language_section
            )
            self.reminder = USER_REPORT_QUERY.format(research_topic=self.research_topic)
        else:
            tool_context = ToolContext(
                citation_mapping=dict(self.citation_mapping),
                next_citation_num=self.citation_processor.get_next_citation_number(),
                url_snippet_map=extract_url_snippet_map(
                    list(self.citation_processor.citation_to_doc.values())
                ),
            )
            context.tools = [
                bind_tool(tool, tool_context, sequential=True) for tool in self.tools
            ]
            for definition in get_research_agent_additional_tool_definitions(
                not self.is_reasoning_model
            ):
                function = definition["function"]
                context.tools.append(
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
            self._prepare_research_instructions(step)
        context.output_metadata = ResearchStepOutput(
            phase=ResearchPhase.REPORT
            if self.is_final_step
            else ResearchPhase.RESEARCH,
            is_intermediate=True,
            is_reasoning_model=self.is_reasoning_model,
            sources=dict(self.citation_processor.citation_to_doc),
        )
        return context

    def _prepare_research_instructions(self, step: AgentStep) -> None:
        tool_names = {tool.name for tool in self.tools}
        has_open_url = OpenURLTool.NAME in tool_names
        template = (
            RESEARCH_AGENT_PROMPT_REASONING
            if self.is_reasoning_model
            else RESEARCH_AGENT_PROMPT
        )
        self.system_prompt = template.format(
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
        self.reminder = (
            OPEN_URL_REMINDER_RESEARCH_AGENT
            if self.just_ran_web_search and has_open_url
            else None
        )

    def _build_request(self, context: AgentContext) -> GenerationRequest:
        context.messages = prepare_model_messages(
            prepare_prompt(
                system_prompt=SystemMessage(content=self.system_prompt),
                custom_agent_prompt=None,
                messages=context.messages,
                reminder_message=UserMessage(
                    content=self.reminder, metadata=PromptMetadata(is_reminder=True)
                )
                if self.reminder
                else None,
                context_files=None,
                token_counter=self.token_counter,
            ),
            self.llm.info,
        )
        return context.generation_request()

    def _after_step(self, result: StepResult) -> bool:
        if self.is_final_step:
            return False
        self.just_ran_web_search = False
        for response in result.tool_results:
            if response.tool_name == GENERATE_REPORT_TOOL_NAME:
                self.requested_final = True
            if isinstance(response.details, SearchDocsResponse):
                self.citation_mapping.update(response.details.citation_mapping)
                self.just_ran_web_search |= (
                    bool(response.details.search_docs)
                    and response.tool_name == WebSearchTool.NAME
                )
                update_citation_processor_from_tool_result(
                    response, self.citation_processor
                )
        if not result.message.tool_calls:
            self.requested_final = True
        return True

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
