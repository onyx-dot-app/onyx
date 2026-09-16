import time
from collections.abc import Callable
from functools import partial

from onyx.agents.models import (
    AgentContext,
    PreparedStep,
    StepInput,
    StepResult,
    ToolCallContext,
)
from onyx.agents.runtime import Agent
from onyx.agents.transcript import CompactionCheckpoint
from onyx.chat.artifacts import ChatArtifacts, ChatSearchResult
from onyx.chat.context import (
    ChatContext,
    ChatReminders,
)
from onyx.chat.errors import _build_empty_llm_response_error
from onyx.chat.files import build_python_chat_files_from_search_docs
from onyx.chat.models import ChatMessageMetadata, PersonaPromptConfig
from onyx.configs.chat_configs import MAX_LLM_CYCLES
from onyx.context.prompt import prepare_prompt
from onyx.context.search.models import SearchDocsResponse
from onyx.db.memory import UserMemoryContext
from onyx.file_store.models import ExtractedContextFiles, FileToolMetadata
from onyx.llm.interfaces import LLM, GenerationContext, LLMUserIdentity
from onyx.llm.models import (
    AssistantMessage,
    GenerationOptions,
    Message,
    NamedToolChoice,
    ReasoningEffort,
    ToolChoiceOptions,
    ToolResult,
    ToolResultMessage,
)
from onyx.tools.interface import Tool, ToolContext
from onyx.tools.models import ChatFile
from onyx.tools.tool_implementations.web_search.utils import extract_url_snippet_map
from onyx.tools.tool_runner import bind_tool
from onyx.tracing.flows import LLMFlow


class ChatAgent:
    """Chat step preparation and result handling for the shared runtime."""

    def __init__(
        self,
        messages: list[Message],
        tools: list[Tool],
        custom_agent_prompt: str | None,
        base_system_prompt: str,
        context_files: ExtractedContextFiles,
        persona: PersonaPromptConfig | None,
        user_memory_context: UserMemoryContext | None,
        llm: LLM,
        token_counter: Callable[[str], int],
        forced_tool_id: int | None = None,
        user_identity: LLMUserIdentity | None = None,
        chat_files: list[ChatFile] | None = None,
        reasoning_effort: ReasoningEffort = ReasoningEffort.AUTO,
        include_citations: bool = True,
        all_injected_file_metadata: dict[str, FileToolMetadata] | None = None,
        inject_memories_in_prompt: bool = True,
        reminders: ChatReminders | None = None,
        checkpoint: CompactionCheckpoint | None = None,
        previous_run_id: str | None = None,
    ) -> None:
        self.max_steps = MAX_LLM_CYCLES
        self.context_files = context_files
        self.token_counter = token_counter
        self.file_metadata = all_injected_file_metadata
        self.tools = [tool.for_agent() for tool in tools]
        self.include_citations = include_citations
        self.llm = llm
        self.reasoning_effort = reasoning_effort
        self.memory = user_memory_context
        self.inject_memories = inject_memories_in_prompt
        self.started = time.monotonic()
        self.forced_tool_id = forced_tool_id
        self.artifacts = ChatArtifacts(
            context_files, chat_files or [], include_citations
        )
        self.context = ChatContext(
            tools=self.tools,
            persona=persona,
            custom_prompt=custom_agent_prompt,
            base_prompt=base_system_prompt,
            files=context_files,
            memory=user_memory_context,
            reminders=reminders or ChatReminders(),
            inject_memories=inject_memories_in_prompt,
        )
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
                flow=LLMFlow.CHAT_RESPONSE, user_identity=user_identity
            ),
            after_tool_call=self._finalize_tool,
        )

    def prepare_step(self, state: StepInput) -> PreparedStep:
        previous = state.previous
        if previous is None:
            self.started = time.monotonic()
            self.artifacts.gathered_documents = list(
                self.artifacts.initial_citations.values()
            )
            assistant = None
            for message in state.history:
                if isinstance(message, AssistantMessage):
                    assistant = message
                elif isinstance(message, ToolResultMessage) and assistant is not None:
                    self.artifacts.update_context(assistant, [message])
            self.artifacts.ran_image_gen = False
        results = [
            message
            for message in state.messages
            if isinstance(message, ToolResultMessage)
        ]
        tools = self.tools
        tool_choice = ToolChoiceOptions.AUTO
        if self.forced_tool_id is not None and state.step.index == 0:
            tools = [tool for tool in tools if tool.id == self.forced_tool_id]
            if not tools:
                raise ValueError(f"Tool {self.forced_tool_id} not found")
            tool_choice = ToolChoiceOptions.REQUIRED
        elif state.step.is_last or self.artifacts.ran_image_gen:
            tools = []
            tool_choice = ToolChoiceOptions.NONE
        prompt = self.context.prepare(
            results,
            previous.tool_results if previous else [],
            is_last_step=state.step.is_last,
            ran_image_gen=self.artifacts.ran_image_gen,
        )
        tool_context = ToolContext(
            user_memory_context=self.memory,
            citation_mapping=dict(self.artifacts.citation_mapping),
            next_citation_num=self.artifacts.citation_processor.get_next_citation_number(),
            skip_search_query_expansion=self.artifacts.has_called_search_tool,
            chat_files=list(self.artifacts.chat_files),
            url_snippet_map=extract_url_snippet_map(self.artifacts.gathered_documents),
            inject_memories_in_prompt=self.inject_memories,
        )
        return PreparedStep(
            tools=[bind_tool(tool, tool_context) for tool in tools],
            options=GenerationOptions(
                tool_choice=tool_choice, reasoning_effort=self.reasoning_effort
            ),
            output_metadata=ChatMessageMetadata(
                sources=dict(self.artifacts.citation_processor.citation_to_doc),
                documents=list(self.artifacts.gathered_documents),
                include_citations=self.include_citations,
                elapsed_seconds=time.monotonic() - self.started,
            ),
            assemble_messages=partial(
                prepare_prompt,
                system_prompt=prompt.system_prompt,
                custom_agent_prompt=prompt.custom_prompt,
                reminder_message=prompt.reminder,
                context_files=self.context_files.model_copy(deep=True),
                token_counter=self.token_counter,
                all_injected_file_metadata=dict(self.file_metadata)
                if self.file_metadata
                else None,
                llm_info=self.llm.info,
            ),
        )

    def after_step(self, result: StepResult) -> bool:
        self.artifacts.update_context(result.message, result.tool_results)
        if not result.message.tool_calls or result.step.is_last:
            self._validate_answer(result)
        return bool(result.message.tool_calls) and not (
            result.tool_results and all(item.terminate for item in result.tool_results)
        )

    def _finalize_tool(
        self, _context: ToolCallContext, result: ToolResult
    ) -> ToolResult:
        if isinstance(result.details, SearchDocsResponse):
            search = result.details
            result.details = ChatSearchResult(
                search_docs=search.search_docs,
                citation_mapping=search.citation_mapping,
                displayed_docs=search.displayed_docs,
                staged_files=build_python_chat_files_from_search_docs(
                    search.search_docs
                ),
            )
        return result

    def _validate_answer(self, result: StepResult) -> None:
        if not result.message.text and not result.message.tool_calls:
            raise _build_empty_llm_response_error(
                llm=self.llm,
                message=result.message,
                tool_choice=(
                    ToolChoiceOptions.REQUIRED
                    if isinstance(result.request.options.tool_choice, NamedToolChoice)
                    else result.request.options.tool_choice
                ),
            )
        if not result.message.text:
            raise RuntimeError(
                "The model did not return a final answer after tool execution."
            )
        return None
