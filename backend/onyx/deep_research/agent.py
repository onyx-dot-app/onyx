import time
from collections.abc import Callable

from pydantic import BaseModel

from onyx.agents.runtime import (
    Agent,
    AgentContext,
    AgentHooks,
    AgentStep,
    StepResult,
    ToolCallContext,
)
from onyx.agents.tools import AgentTool, ToolInvocation, ToolProgress
from onyx.agents.transcript import CompactionCheckpoint
from onyx.chat.citation_processor import CitationMapping, DynamicCitationProcessor
from onyx.chat.citation_utils import (
    collapse_citations,
    extract_citation_order_from_text,
)
from onyx.chat.prompt_utils import with_language_section
from onyx.configs.chat_configs import (
    DR_REPORT_LLM_TIMEOUT_S,
)
from onyx.context.messages import PromptMetadata, prepare_model_messages
from onyx.context.prompt import prepare_prompt
from onyx.deep_research.models import (
    ResearchAgentCallResult,
    ResearchPhase,
    ResearchStepOutput,
)
from onyx.deep_research.research_agent import ResearchAgent
from onyx.deep_research.tool_definitions import (
    GENERATE_REPORT_TOOL_NAME,
    RESEARCH_AGENT_TOOL_NAME,
    THINK_TOOL_RESPONSE_MESSAGE,
    get_clarification_tool_definitions,
    get_orchestrator_tools,
)
from onyx.file_store.models import FileToolMetadata
from onyx.llm.exceptions import ClassifiedLLMError, LLMRateLimitError, LLMTimeoutError
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
from onyx.prompts.deep_research.research_agent import MAX_RESEARCH_CYCLES
from onyx.prompts.prompt_utils import get_current_llm_day_time
from onyx.tools.interface import FunctionToolDefinition, Tool, parse_tool_arguments
from onyx.tools.progress import ResearchStarted
from onyx.tools.tool_implementations.open_url.open_url_tool import OpenURLTool
from onyx.tools.tool_implementations.search.search_tool import SearchTool
from onyx.tools.tool_implementations.web_search.web_search_tool import WebSearchTool
from onyx.tracing.flows import LLMFlow
from onyx.utils.logger import setup_logger

logger = setup_logger()

MAX_FINAL_REPORT_TOKENS = 20000
ORCHESTRATION_OUTPUT_TOKENS = 1024
MIN_RESEARCH_CONTEXT_TOKENS = 50000
MAX_ORCHESTRATOR_CYCLES = 8
MAX_ORCHESTRATOR_CYCLES_REASONING = 4


class ResearchTask(BaseModel):
    task: str


class DeepResearchAgent:
    """Clarify a question, coordinate research children, and write a report."""

    def __init__(
        self,
        messages: list[Message],
        allowed_tools: list[Tool],
        llm: LLM,
        token_counter: Callable[[str], int],
        user_identity: LLMUserIdentity | None,
        language_section: str,
        reasoning_effort: ReasoningEffort,
        all_injected_file_metadata: dict[str, FileToolMetadata] | None,
        skip_clarification: bool = False,
        checkpoint: CompactionCheckpoint | None = None,
    ) -> None:
        allowed_names = {SearchTool.NAME, WebSearchTool.NAME, OpenURLTool.NAME}
        self.tools = [tool for tool in allowed_tools if tool.name in allowed_names]
        self.llm = llm
        self.token_counter = token_counter
        self.user_identity = user_identity
        self.language_section = language_section
        self.reasoning_effort = reasoning_effort
        self.file_metadata = all_injected_file_metadata
        self.started = time.monotonic()
        self.plan = ""
        self.phase = (
            ResearchPhase.PLANNING
            if skip_clarification
            else ResearchPhase.CLARIFICATION
        )
        self.research_steps = 0
        self.is_reasoning_model = model_is_reasoning_model(
            llm.info.model_name, llm.info.model_provider
        )
        self.max_orchestrator_cycles = (
            MAX_ORCHESTRATOR_CYCLES_REASONING
            if self.is_reasoning_model
            else MAX_ORCHESTRATOR_CYCLES
        )
        self.max_steps = self.max_orchestrator_cycles + (1 if skip_clarification else 2)
        self.has_internal_search = any(
            tool.name == SearchTool.NAME for tool in self.tools
        )
        self.citation_mapping: CitationMapping = {}
        self.report_citations = DynamicCitationProcessor()
        self.system_prompt = ""
        self.reminder: str | None = None
        self.agent = Agent(
            llm,
            context=AgentContext(
                messages=messages,
                checkpoint=checkpoint,
                execution=GenerationContext(flow=LLMFlow.DEEP_RESEARCH),
            ),
            hooks=AgentHooks(
                prepare_step=self._prepare_step,
                build_request=self._build_request,
                after_tool_call=self._finalize_tool,
                after_step=self._after_step,
            ),
        )

    def _prepare_step(self, context: AgentContext, step: AgentStep) -> AgentContext:
        if self.phase == ResearchPhase.RESEARCH and step.is_last:
            self.phase = ResearchPhase.REPORT
        context.execution.user_identity = self.user_identity
        context.options.reasoning_effort = self.reasoning_effort
        context.execution.timeout = (
            DR_REPORT_LLM_TIMEOUT_S if self.phase == ResearchPhase.REPORT else None
        )
        context.options.max_tokens = (
            MAX_FINAL_REPORT_TOKENS
            if self.phase == ResearchPhase.REPORT
            else ORCHESTRATION_OUTPUT_TOKENS
        )
        context.tools = []
        context.options.tool_choice = ToolChoiceOptions.NONE
        self.reminder = None
        now = get_current_llm_day_time(full_sentence=False)
        if self.phase == ResearchPhase.CLARIFICATION:
            self.system_prompt = with_language_section(
                CLARIFICATION_PROMPT.format(
                    current_datetime=now,
                    internal_search_clarification_guidance=INTERNAL_SEARCH_CLARIFICATION_GUIDANCE
                    if self.has_internal_search
                    else "",
                ),
                self.language_section,
            )
            context.tools = [
                self._control_tool(definition, "Proceed to planning.")
                for definition in get_clarification_tool_definitions()
            ]
            context.options.tool_choice = ToolChoiceOptions.AUTO
        elif self.phase == ResearchPhase.PLANNING:
            self.system_prompt = RESEARCH_PLAN_PROMPT.format(current_datetime=now)
            self.reminder = RESEARCH_PLAN_REMINDER
        elif self.phase == ResearchPhase.RESEARCH:
            template = (
                ORCHESTRATOR_PROMPT_REASONING
                if self.is_reasoning_model
                else ORCHESTRATOR_PROMPT
            )
            self.system_prompt = template.format(
                current_datetime=now,
                current_cycle_count=self.research_steps,
                max_cycles=self.max_orchestrator_cycles,
                research_plan=self.plan,
                internal_search_research_task_guidance=INTERNAL_SEARCH_RESEARCH_TASK_GUIDANCE
                if self.has_internal_search
                else "",
            )
            self.reminder = FIRST_CYCLE_REMINDER if self.research_steps == 1 else None
            for definition in get_orchestrator_tools(not self.is_reasoning_model):
                function = definition["function"]
                context.tools.append(
                    AgentTool(
                        name=function["name"],
                        description=function["description"],
                        parameters=function["parameters"],
                        execute_async=self._research,
                    )
                    if function["name"] == RESEARCH_AGENT_TOOL_NAME
                    else self._control_tool(
                        definition,
                        "Ready to produce the final report."
                        if function["name"] == GENERATE_REPORT_TOOL_NAME
                        else THINK_TOOL_RESPONSE_MESSAGE,
                    )
                )
            context.options.tool_choice = ToolChoiceOptions.REQUIRED
        else:
            self.system_prompt = with_language_section(
                FINAL_REPORT_PROMPT.format(current_datetime=now), self.language_section
            )
            self.reminder = USER_FINAL_REPORT_QUERY.format(research_plan=self.plan)
            self.report_citations = DynamicCitationProcessor()
            self.report_citations.update_citation_mapping(self.citation_mapping)
        context.output_metadata = ResearchStepOutput(
            phase=self.phase,
            is_reasoning_model=self.is_reasoning_model,
            sources=dict(self.citation_mapping),
            elapsed_seconds=time.monotonic() - self.started,
        )
        return context

    @staticmethod
    def _control_tool(definition: FunctionToolDefinition, result: str) -> AgentTool:
        function = definition["function"]
        return AgentTool(
            name=function["name"],
            description=function["description"],
            parameters=function["parameters"],
            execute=lambda _invocation: ToolResult(content=result),
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
                all_injected_file_metadata=self.file_metadata,
            ),
            self.llm.info,
        )
        return context.generation_request()

    async def _research(self, invocation: ToolInvocation) -> ToolResult:
        task = parse_tool_arguments(ResearchTask, invocation.arguments)
        invocation.update(
            ToolProgress(details=ResearchStarted(research_task=task.task))
        )
        child = ResearchAgent(
            research_topic=task.task,
            tools=self.tools,
            llm=self.llm,
            is_reasoning_model=self.is_reasoning_model,
            token_counter=self.token_counter,
            user_identity=self.user_identity,
            language_section=self.language_section,
            reasoning_effort=self.reasoning_effort
            if self.reasoning_effort != ReasoningEffort.AUTO
            else ReasoningEffort.LOW,
        )
        try:
            completed = await invocation.run_child(
                child.agent,
                max_steps=MAX_RESEARCH_CYCLES + 1,
                messages=child.input_messages,
            )
        except (ClassifiedLLMError, LLMTimeoutError, LLMRateLimitError):
            logger.exception("Research child generation failed")
            return ToolResult(
                content="Research failed. Continue with other sources or try a different task.",
                is_error=True,
            )
        result = child.report(completed)
        return ToolResult(content=result.intermediate_report, details=result)

    def _finalize_tool(
        self, _context: ToolCallContext, result: ToolResult
    ) -> ToolResult:
        if isinstance(result.details, ResearchAgentCallResult):
            report, self.citation_mapping = collapse_citations(
                answer_text=result.text,
                existing_citation_mapping=self.citation_mapping,
                new_citation_mapping=result.details.citation_mapping,
            )
            result.content = report
            result.details = ResearchAgentCallResult(
                intermediate_report=report,
                citation_mapping={
                    number: self.citation_mapping[number]
                    for number in extract_citation_order_from_text(report)
                    if number in self.citation_mapping
                },
            )
        return result

    def _after_step(self, result: StepResult) -> bool:
        if self.phase == ResearchPhase.CLARIFICATION:
            if result.message.tool_calls:
                self.phase = ResearchPhase.PLANNING
                return True
            return False
        if self.phase == ResearchPhase.PLANNING:
            self.plan = result.message.text
            if not self.plan:
                raise ValueError("Model failed to produce a research plan")
            self.phase = ResearchPhase.RESEARCH
            return True
        if self.phase == ResearchPhase.REPORT:
            if not result.message.text:
                raise ValueError("Model failed to produce the final report")
            return False
        self.research_steps += 1
        if not result.message.tool_calls or any(
            response.tool_name == GENERATE_REPORT_TOOL_NAME
            for response in result.tool_results
        ):
            self.phase = ResearchPhase.REPORT
        return True
