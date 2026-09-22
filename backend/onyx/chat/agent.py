import time
from collections.abc import Callable
from functools import partial

from pydantic import BaseModel

from onyx.agents.models import (
    AgentContext,
    PreparedStep,
    StepInput,
    StepResult,
    ToolCallContext,
)
from onyx.agents.restoration import FeatureRestoration
from onyx.agents.runtime import Agent
from onyx.agents.transcript import CompactionCheckpoint
from onyx.chat.artifacts import ChatArtifacts, ChatSearchResult
from onyx.chat.context import (
    ChatContext,
    ChatReminders,
)
from onyx.chat.errors import _build_empty_llm_response_error
from onyx.chat.files import build_python_chat_files_from_search_docs
from onyx.chat.models import (
    ChatFeatureState,
    ChatMessageMetadata,
    ChatRestoreConfiguration,
    PersonaPromptConfig,
)
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
from onyx.tools.file_snapshot import SavedChatFile, SavedContextFiles
from onyx.tools.interface import Tool, ToolContext
from onyx.tools.models import ChatFile
from onyx.tools.restoration import (
    capture_search_state,
    restore_search_state,
)
from onyx.tools.tool_implementations.web_search.utils import extract_url_snippet_map
from onyx.tools.tool_runner import bind_tool
from onyx.tracing.flows import LLMFlow


class ChatAgent(FeatureRestoration):
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
        agent_id: str | None = None,
    ) -> None:
        self.max_steps = MAX_LLM_CYCLES
        self.custom_agent_prompt = custom_agent_prompt
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
            tools=[bind_tool(tool, self._tool_context) for tool in self.tools],
            agent_id=agent_id,
            previous_run_id=previous_run_id,
            context=AgentContext(
                messages=messages,
                checkpoint=checkpoint,
            ),
            restoration=self,
            prepare_step=self.prepare_step,
            after_step=self.after_step,
            execution=GenerationContext(
                flow=LLMFlow.CHAT_RESPONSE, user_identity=user_identity
            ),
            after_tool_call=self._finalize_tool,
        )

    def _restoration_configuration(self) -> ChatRestoreConfiguration:
        return ChatRestoreConfiguration(
            persona=self.context.persona,
            context_files=SavedContextFiles.capture(self.context_files),
            file_metadata=self.file_metadata,
            memory=self.memory,
            reasoning_effort=self.reasoning_effort,
            include_citations=self.include_citations,
            inject_memories=self.inject_memories,
            forced_tool_id=self.forced_tool_id,
            base_prompt=self.context.base_prompt,
            custom_prompt=self.custom_agent_prompt,
            reminders_enabled=self.context.reminders.enabled,
        )

    def capture_state(self) -> ChatFeatureState:
        return ChatFeatureState(
            configuration=self._restoration_configuration(),
            elapsed_seconds=max(0.0, time.monotonic() - self.started),
            citation_sources=self.artifacts.citation_processor.citation_to_doc,
            citation_mapping=self.artifacts.citation_mapping,
            gathered_documents=self.artifacts.gathered_documents,
            chat_files=[
                SavedChatFile.capture(file) for file in self.artifacts.chat_files
            ],
            has_called_search_tool=self.artifacts.has_called_search_tool,
            ran_image_gen=self.artifacts.ran_image_gen,
            search_tools=capture_search_state(self.tools),
        ).model_copy(deep=True)

    def restore_state(self, state: BaseModel) -> None:
        if not isinstance(state, ChatFeatureState):
            raise ValueError("Chat restoration requires ChatFeatureState")
        saved = state.model_copy(deep=True)
        if saved.configuration != self._restoration_configuration():
            raise ValueError("Chat restoration configuration does not match")
        restore_search_state(self.tools, saved.search_tools)
        self.started = time.monotonic() - saved.elapsed_seconds
        self.artifacts.citation_processor.citation_to_doc = saved.citation_sources
        self.artifacts.citation_mapping = saved.citation_mapping
        self.artifacts.gathered_documents = saved.gathered_documents
        self.artifacts.chat_files = [file.restore() for file in saved.chat_files]
        self.artifacts.has_called_search_tool = saved.has_called_search_tool
        self.artifacts.ran_image_gen = saved.ran_image_gen

    def _tool_context(self) -> ToolContext:
        """Read feature state that advances only after a completed step."""
        return ToolContext(
            user_memory_context=self.memory,
            citation_mapping=dict(self.artifacts.citation_mapping),
            next_citation_num=self.artifacts.citation_processor.get_next_citation_number(),
            skip_search_query_expansion=self.artifacts.has_called_search_tool,
            chat_files=list(self.artifacts.chat_files),
            url_snippet_map=extract_url_snippet_map(self.artifacts.gathered_documents),
            inject_memories_in_prompt=self.inject_memories,
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
        selected_names = {tool.name for tool in tools}
        return PreparedStep(
            tools=[tool for tool in self.agent.tools if tool.name in selected_names],
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
                queries=search.queries,
                sources=search.sources,
                time_filter_start=search.time_filter_start,
                time_filter_end=search.time_filter_end,
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
                    if isinstance(result.options.tool_choice, NamedToolChoice)
                    else result.options.tool_choice
                ),
            )
        if not result.message.text:
            raise RuntimeError(
                "The model did not return a final answer after tool execution."
            )
        return None
