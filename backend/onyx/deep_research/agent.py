import time
from collections.abc import Callable
from functools import partial
from threading import Lock

from pydantic import BaseModel

from onyx.agents.models import (
    AgentContext,
    PreparedStep,
    StepInput,
    StepResult,
)
from onyx.agents.runtime import Agent, RunFailed
from onyx.agents.tools import AgentTool, ToolInvocation
from onyx.agents.transcript import (
    AgentRestorationConfig,
    CompactionCheckpoint,
    RunFailureKind,
)
from onyx.chat.citation_processor import CitationMapping
from onyx.chat.citation_utils import (
    collapse_citations,
    extract_citation_order_from_text,
)
from onyx.chat.prompt_utils import with_language_section
from onyx.configs.chat_configs import (
    DR_REPORT_LLM_TIMEOUT_S,
)
from onyx.context.messages import PromptMetadata
from onyx.context.prompt import prepare_prompt
from onyx.deep_research.models import (
    ResearchAgentCallResult,
    ResearchMessageMetadata,
    ResearchPhase,
)
from onyx.deep_research.research_agent import ResearchAgent, ResearchConfiguration
from onyx.deep_research.tool_definitions import (
    GENERATE_REPORT_TOOL_NAME,
    RESEARCH_AGENT_TOOL_NAME,
    THINK_TOOL_RESPONSE_MESSAGE,
    get_clarification_tool_definitions,
    get_orchestrator_tools,
)
from onyx.file_store.models import FileToolMetadata
from onyx.llm.interfaces import LLM, GenerationContext, LLMUserIdentity
from onyx.llm.model_capabilities import model_is_reasoning_model
from onyx.llm.models import (
    AssistantMessage,
    GenerationOptions,
    Message,
    ReasoningEffort,
    SystemMessage,
    ToolChoiceOptions,
    ToolResult,
    ToolResultMessage,
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
from onyx.tools.tool_implementations.search.search_tool import SearchTool
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
        previous_run_id: str | None = None,
    ) -> None:
        self.tools = allowed_tools
        self.llm = llm
        self.token_counter = token_counter
        self.user_identity = user_identity
        self.language_section = language_section
        self.reasoning_effort = reasoning_effort
        self.file_metadata = all_injected_file_metadata
        self.started = time.monotonic()
        self.skip_clarification = skip_clarification
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
        self._citation_lock = Lock()
        self.agent = Agent(
            llm,
            previous_run_id=previous_run_id,
            context=AgentContext(
                messages=messages,
                checkpoint=checkpoint,
            ),
            prepare_step=self.prepare_step,
            after_step=self.after_step,
            execution=GenerationContext(
                flow=LLMFlow.DEEP_RESEARCH, user_identity=user_identity
            ),
        )

    def prepare_step(self, state: StepInput) -> PreparedStep:
        if state.previous is None:
            self.started = time.monotonic()
            for message in state.history:
                if isinstance(message, ToolResultMessage) and isinstance(
                    message.details, ResearchAgentCallResult
                ):
                    with self._citation_lock:
                        self.citation_mapping.update(message.details.citation_mapping)
        phase = self._next_phase(state)
        plan = ""
        research_steps = 0
        for message in state.messages:
            if not isinstance(message, AssistantMessage) or not isinstance(
                message.metadata, ResearchMessageMetadata
            ):
                continue
            if message.metadata.phase == ResearchPhase.PLANNING:
                plan = message.text
            elif message.metadata.phase == ResearchPhase.RESEARCH:
                research_steps += 1
        options = GenerationOptions()
        options.reasoning_effort = self.reasoning_effort
        options.max_tokens = (
            MAX_FINAL_REPORT_TOKENS
            if phase == ResearchPhase.REPORT
            else ORCHESTRATION_OUTPUT_TOKENS
        )
        tools = []
        options.tool_choice = ToolChoiceOptions.NONE
        reminder = None
        now = get_current_llm_day_time(full_sentence=False)
        if phase == ResearchPhase.CLARIFICATION:
            system_prompt = with_language_section(
                CLARIFICATION_PROMPT.format(
                    current_datetime=now,
                    internal_search_clarification_guidance=INTERNAL_SEARCH_CLARIFICATION_GUIDANCE
                    if self.has_internal_search
                    else "",
                ),
                self.language_section,
            )
            tools = [
                self._control_tool(definition, "Proceed to planning.")
                for definition in get_clarification_tool_definitions()
            ]
            options.tool_choice = ToolChoiceOptions.AUTO
        elif phase == ResearchPhase.PLANNING:
            system_prompt = RESEARCH_PLAN_PROMPT.format(current_datetime=now)
            reminder = RESEARCH_PLAN_REMINDER
        elif phase == ResearchPhase.RESEARCH:
            template = (
                ORCHESTRATOR_PROMPT_REASONING
                if self.is_reasoning_model
                else ORCHESTRATOR_PROMPT
            )
            system_prompt = template.format(
                current_datetime=now,
                current_cycle_count=research_steps,
                max_cycles=self.max_orchestrator_cycles,
                research_plan=plan,
                internal_search_research_task_guidance=INTERNAL_SEARCH_RESEARCH_TASK_GUIDANCE
                if self.has_internal_search
                else "",
            )
            reminder = FIRST_CYCLE_REMINDER if research_steps == 1 else None
            for definition in get_orchestrator_tools(not self.is_reasoning_model):
                function = definition["function"]
                tools.append(
                    AgentTool(
                        name=function["name"],
                        description=function["description"],
                        parameters=function["parameters"],
                        execute=self._research,
                    )
                    if function["name"] == RESEARCH_AGENT_TOOL_NAME
                    else self._control_tool(
                        definition,
                        "Ready to produce the final report."
                        if function["name"] == GENERATE_REPORT_TOOL_NAME
                        else THINK_TOOL_RESPONSE_MESSAGE,
                    )
                )
            options.tool_choice = ToolChoiceOptions.REQUIRED
        else:
            system_prompt = with_language_section(
                FINAL_REPORT_PROMPT.format(current_datetime=now), self.language_section
            )
            reminder = USER_FINAL_REPORT_QUERY.format(research_plan=plan)
        with self._citation_lock:
            sources = dict(self.citation_mapping)
        output_metadata = ResearchMessageMetadata(
            phase=phase,
            is_reasoning_model=self.is_reasoning_model,
            sources=sources,
            elapsed_seconds=time.monotonic() - self.started,
        )
        return PreparedStep(
            tools=tools,
            options=options,
            timeout=DR_REPORT_LLM_TIMEOUT_S if phase == ResearchPhase.REPORT else None,
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
                all_injected_file_metadata=dict(self.file_metadata)
                if self.file_metadata
                else None,
            ),
        )

    def _next_phase(self, state: StepInput) -> ResearchPhase:
        previous = state.previous
        if previous is None:
            return (
                ResearchPhase.PLANNING
                if self.skip_clarification
                else ResearchPhase.CLARIFICATION
            )
        metadata = previous.message.metadata
        if not isinstance(metadata, ResearchMessageMetadata):
            raise ValueError("Research output requires phase metadata")
        if metadata.phase == ResearchPhase.CLARIFICATION:
            return ResearchPhase.PLANNING
        if metadata.phase != ResearchPhase.PLANNING and (
            not previous.message.tool_calls
            or any(
                result.tool_name == GENERATE_REPORT_TOOL_NAME
                for result in previous.tool_results
            )
        ):
            return ResearchPhase.REPORT
        return ResearchPhase.REPORT if state.step.is_last else ResearchPhase.RESEARCH

    def after_step(self, result: StepResult) -> bool:
        metadata = result.message.metadata
        if not isinstance(metadata, ResearchMessageMetadata):
            raise ValueError("Research output requires phase metadata")
        if metadata.phase == ResearchPhase.CLARIFICATION:
            return bool(result.message.tool_calls)
        if metadata.phase == ResearchPhase.REPORT:
            if not result.message.text:
                raise ValueError("Model failed to produce the final report")
            return False
        if metadata.phase == ResearchPhase.PLANNING and not result.message.text:
            raise ValueError("Model failed to produce a research plan")
        return True

    @staticmethod
    def _control_tool(definition: FunctionToolDefinition, result: str) -> AgentTool:
        function = definition["function"]
        return AgentTool(
            name=function["name"],
            description=function["description"],
            parameters=function["parameters"],
            execute=lambda _invocation: ToolResult(content=result),
        )

    def _research(self, invocation: ToolInvocation) -> ToolResult:
        task = parse_tool_arguments(ResearchTask, invocation.arguments)
        child = ResearchAgent(
            tools=self.tools,
            llm=self.llm,
            token_counter=self.token_counter,
            user_identity=self.user_identity,
            language_section=self.language_section,
            reasoning_effort=self.reasoning_effort
            if self.reasoning_effort != ReasoningEffort.AUTO
            else ReasoningEffort.LOW,
        )
        try:
            submission = invocation.agents.spawn_agent(
                child.agent,
                name="research-"
                + "".join(
                    char if char.isascii() and char.isalnum() else "-"
                    for char in invocation.call_id.lower()
                ),
                description=task.task,
                max_steps=MAX_RESEARCH_CYCLES + 1,
                messages=[UserMessage(content=task.task)],
                restoration_config=AgentRestorationConfig(
                    feature="research",
                    settings=ResearchConfiguration(
                        language_section=self.language_section,
                        reasoning_effort=self.reasoning_effort
                        if self.reasoning_effort != ReasoningEffort.AUTO
                        else ReasoningEffort.LOW,
                    ).model_dump(mode="json"),
                ),
            )
            while (completed := invocation.agents.wait_run(submission.run_id)) is None:
                invocation.cancellation.check()

        except RunFailed as error:
            if error.failure.kind not in {
                RunFailureKind.LLM,
                RunFailureKind.LLM_TIMEOUT,
                RunFailureKind.LLM_RATE_LIMIT,
            }:
                raise
            logger.exception("Research child generation failed")
            return ToolResult(
                content="Research failed. Continue with other sources or try a different task.",
                is_error=True,
            )
        result = child.report(completed)
        with self._citation_lock:
            report, self.citation_mapping = collapse_citations(
                answer_text=result.intermediate_report,
                existing_citation_mapping=self.citation_mapping,
                new_citation_mapping=result.citation_mapping,
            )
            citations = {
                number: self.citation_mapping[number]
                for number in extract_citation_order_from_text(report)
                if number in self.citation_mapping
            }
        return ToolResult(
            content=report,
            details=ResearchAgentCallResult(
                intermediate_report=report,
                citation_mapping=citations,
            ),
        )
