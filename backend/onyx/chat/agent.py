import time
from collections.abc import Callable

from onyx.agents.runtime import (
    Agent,
    AgentContext,
    AgentHooks,
    AgentStep,
    StepResult,
    ToolCallContext,
)
from onyx.agents.transcript import CompactionCheckpoint
from onyx.chat.artifacts import ChatArtifacts, ChatSearchResult
from onyx.chat.context_policy import (
    ChatContextPolicy,
    ChatReminderPolicy,
    PreparedChatStep,
)
from onyx.chat.errors import _build_empty_llm_response_error
from onyx.chat.files import build_python_chat_files_from_search_docs
from onyx.chat.models import ChatStepOutput, PersonaPromptConfig
from onyx.context.messages import prepare_model_messages
from onyx.context.prompt import prepare_prompt
from onyx.context.search.models import SearchDocsResponse
from onyx.db.memory import UserMemoryContext
from onyx.file_store.models import ExtractedContextFiles, FileToolMetadata
from onyx.llm.interfaces import LLM, GenerationContext, LLMUserIdentity
from onyx.llm.models import GenerationRequest, Message, ReasoningEffort, ToolResult
from onyx.tools.interface import Tool, ToolContext
from onyx.tools.models import ChatFile
from onyx.tools.tool_implementations.web_search.utils import extract_url_snippet_map
from onyx.tools.tool_runner import bind_tool
from onyx.tracing.flows import LLMFlow


class ChatAgent:
    """Chat instructions and result policy composed with the shared runtime."""

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
        reminder_policy: ChatReminderPolicy | None = None,
        checkpoint: CompactionCheckpoint | None = None,
    ) -> None:
        self.context_files = context_files
        self.token_counter = token_counter
        self.file_metadata = all_injected_file_metadata
        self.tools = tools
        self.include_citations = include_citations
        self.llm = llm
        self.user_identity = user_identity
        self.reasoning_effort = reasoning_effort
        self.memory = user_memory_context
        self.inject_memories = inject_memories_in_prompt
        self.started = time.monotonic()
        self.reminders = reminder_policy or ChatReminderPolicy()
        self.artifacts = ChatArtifacts(
            context_files, chat_files or [], include_citations
        )
        self.policy = ChatContextPolicy(
            tools=tools,
            persona=persona,
            custom_prompt=custom_agent_prompt,
            base_prompt=base_system_prompt,
            files=context_files,
            memory=user_memory_context,
            artifacts=self.artifacts,
            reminders=self.reminders,
            forced_tool_id=forced_tool_id,
            inject_memories=inject_memories_in_prompt,
        )
        self.prepared: PreparedChatStep | None = None
        self.agent = Agent(
            llm,
            context=AgentContext(
                messages=messages,
                checkpoint=checkpoint,
                execution=GenerationContext(flow=LLMFlow.CHAT_RESPONSE),
            ),
            hooks=AgentHooks(
                prepare_step=self._prepare_step,
                build_request=self._build_request,
                after_tool_call=self._finalize_tool,
                after_step=self._after_step,
            ),
        )

    def _prepare_step(self, context: AgentContext, step: AgentStep) -> AgentContext:
        self.prepared = self.policy.prepare(step)
        tool_context = ToolContext(
            user_memory_context=self.memory,
            citation_mapping=dict(self.artifacts.citation_mapping),
            next_citation_num=self.artifacts.citation_processor.get_next_citation_number(),
            skip_search_query_expansion=self.artifacts.has_called_search_tool,
            chat_files=self.artifacts.chat_files,
            url_snippet_map=extract_url_snippet_map(self.artifacts.gathered_documents),
            inject_memories_in_prompt=self.inject_memories,
        )
        context.tools = [bind_tool(tool, tool_context) for tool in self.prepared.tools]
        context.options.tool_choice = self.prepared.tool_choice
        context.options.reasoning_effort = self.reasoning_effort
        context.execution.user_identity = self.user_identity
        context.output_metadata = ChatStepOutput(
            sources=dict(self.artifacts.citation_processor.citation_to_doc),
            documents=list(self.artifacts.gathered_documents),
            include_citations=self.include_citations,
            elapsed_seconds=time.monotonic() - self.started,
        )
        return context

    def _build_request(self, context: AgentContext) -> GenerationRequest:
        if self.prepared is None:
            raise RuntimeError("Chat step must be prepared before its request")
        context.messages = prepare_model_messages(
            prepare_prompt(
                system_prompt=self.prepared.system_prompt,
                custom_agent_prompt=self.prepared.custom_prompt,
                messages=context.messages,
                reminder_message=self.prepared.reminder,
                context_files=self.context_files,
                token_counter=self.token_counter,
                all_injected_file_metadata=self.file_metadata,
            ),
            self.llm.info,
        )
        return context.generation_request()

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

    def _after_step(self, result: StepResult) -> bool | None:
        self.reminders.after_tools(result.tool_results)
        self.artifacts.update_context(result.message, result.tool_results)
        if result.message.tool_calls and not result.step.is_last:
            return None
        if self.prepared is None:
            raise RuntimeError("Chat result requires a prepared step")
        if not result.message.text and not result.message.tool_calls:
            raise _build_empty_llm_response_error(
                llm=self.llm,
                message=result.message,
                tool_choice=self.prepared.tool_choice,
            )
        if not result.message.text:
            raise RuntimeError(
                "The model did not return a final answer after tool execution."
            )
        return None
