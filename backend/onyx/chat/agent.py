import time
from collections.abc import Callable

from onyx.agents.events import AgentEndEvent, AgentEvent
from onyx.agents.runtime import (
    Agent,
    AgentContext,
    AgentHooks,
    AgentTurn,
    ToolCallContext,
    TurnResult,
)
from onyx.chat.artifacts import ChatArtifacts, ChatSearchResult
from onyx.chat.chat_state import ChatStateContainer, PersonaPromptConfig
from onyx.chat.context_policy import (
    ChatContextPolicy,
    ChatReminderPolicy,
    PreparedChatTurn,
)
from onyx.chat.emitter import Emitter, NullEmitter
from onyx.chat.errors import _build_empty_llm_response_error
from onyx.chat.files import build_python_chat_files_from_search_docs
from onyx.chat.presentation import TurnPresentation
from onyx.chat.prompt_utils import get_default_base_system_prompt
from onyx.chat.renderer import RenderConfig
from onyx.configs.app_configs import INTEGRATION_TESTS_MODE
from onyx.context.messages import prepare_model_messages
from onyx.context.search.models import SearchDocsResponse
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.memory import UserMemoryContext
from onyx.file_store.models import ExtractedContextFiles, FileToolMetadata
from onyx.llm.cancellation import check_cancelled
from onyx.llm.interfaces import LLM, GenerationContext, LLMUserIdentity
from onyx.llm.models import Message, ReasoningEffort, ToolChoiceOptions, ToolResult
from onyx.server.query_and_chat.placement import Placement
from onyx.server.query_and_chat.streaming_models import (
    OverallStop,
    Packet,
    ToolCallDebug,
    TopLevelBranching,
)
from onyx.tools.interface import Tool
from onyx.tools.models import ChatFile, ToolCallKickoff
from onyx.tools.tool_implementations.memory.memory_tool import MemoryTool
from onyx.tools.tool_implementations.web_search.utils import extract_url_snippet_map
from onyx.tools.tool_runner import (
    LegacyToolContext,
    bind_tool,
    run_tool_call,
)
from onyx.tracing.flows import LLMFlow


class ChatAgent(Agent):
    """Compose Agent with chat context, presentation, and artifact persistence."""

    def __init__(
        self,
        emitter: Emitter | None,
        state_container: ChatStateContainer,
        messages: list[Message],
        tools: list[Tool],
        custom_agent_prompt: str | None,
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
    ) -> None:
        self.emitter = emitter or NullEmitter()
        self.state = state_container
        self.llm = llm
        self.token_counter = token_counter
        self.user_identity = user_identity
        self.reasoning_effort = reasoning_effort
        self.memory = user_memory_context
        self.inject_memories = inject_memories_in_prompt
        self.started = time.monotonic()
        self.reminders = reminder_policy or ChatReminderPolicy()
        self.artifacts = ChatArtifacts(
            context_files,
            chat_files or [],
            include_citations,
        )
        with get_session_with_current_tenant() as session:
            base_prompt = get_default_base_system_prompt(session)
        self.policy = ChatContextPolicy(
            tools=tools,
            persona=persona,
            custom_prompt=custom_agent_prompt,
            base_prompt=base_prompt,
            files=context_files,
            memory=user_memory_context,
            llm_info=llm.info,
            token_counter=token_counter,
            artifacts=self.artifacts,
            reminders=self.reminders,
            forced_tool_id=forced_tool_id,
            file_metadata=all_injected_file_metadata,
            inject_memories=inject_memories_in_prompt,
        )
        self.presentation = TurnPresentation(emitter) if emitter is not None else None
        self.prepared = PreparedChatTurn(
            history=[], tools=[], tool_choice=ToolChoiceOptions.AUTO
        )
        self.display_turn = 0

        super().__init__(
            self.llm,
            context=AgentContext(
                messages=messages,
                execution=GenerationContext(flow=LLMFlow.CHAT_RESPONSE),
            ),
            hooks=AgentHooks(
                transform_context=self._context,
                before_tool_call=self._before_tool,
                after_turn=self._after_turn,
            ),
        )
        self.state.bind_agent(
            self,
            lambda messages: self.artifacts.project(
                messages,
                tools,
                self.presentation.placement_for
                if self.presentation is not None
                else lambda _call_id: Placement(turn_index=0),
            ),
        )
        self.tool_context = LegacyToolContext(lambda: self.context.messages)
        if self.presentation is not None:
            self.subscribe(self.presentation.consume)
        self.subscribe(self._on_complete)

    def _context(self, context: AgentContext, turn: AgentTurn) -> AgentContext:
        self.prepared = self.policy.prepare(list(context.messages), turn)
        context.tools = [
            bind_tool(
                tool.tool_definition(),
                self._execute_tool,
                self.tool_context,
                sequential=isinstance(tool, MemoryTool),
            )
            for tool in self.prepared.tools
        ]
        context.options.tool_choice = self.prepared.tool_choice
        context.options.reasoning_effort = self.reasoning_effort
        context.execution.user_identity = self.user_identity
        config = RenderConfig(
            placement=Placement(turn_index=self.display_turn),
            citations=self.artifacts.citation_processor,
            documents=self.artifacts.gathered_documents or None,
            argument_tools={
                tool.name
                for tool in self.prepared.tools
                if tool.should_emit_argument_deltas()
            },
            pre_answer_seconds=time.monotonic() - self.started,
        )
        if self.presentation is not None:
            self.presentation.configure(config, self.state)
        context.messages = self.prepared.history
        context.messages = prepare_model_messages(context.messages, self.llm.info)
        return context

    def _before_tool(self, context: ToolCallContext) -> ToolResult | None:
        call = self.tool_context.kickoff(
            context.call.id, context.call.name, context.call.arguments
        )
        if INTEGRATION_TESTS_MODE and self.presentation is not None:
            self.presentation.emit_tool_packet(
                context.call.id,
                Packet(
                    placement=call.placement,
                    obj=ToolCallDebug(
                        tool_call_id=call.tool_call_id,
                        tool_name=call.tool_name,
                        tool_args=call.tool_args,
                    ),
                ),
            )
        calls = self.tool_context.message().tool_calls
        if (
            len(calls) > 1
            and context.call.id == calls[0].id
            and self.presentation is not None
        ):
            self.presentation.emit_tool_packet(
                context.call.id,
                Packet(
                    placement=call.placement,
                    obj=TopLevelBranching(num_parallel_branches=len(calls)),
                ),
            )
        return None

    def _execute_tool(self, call: ToolCallKickoff) -> ToolResult:
        result = run_tool_call(
            tool_call=call,
            tool=next(
                tool for tool in self.prepared.tools if tool.name == call.tool_name
            ),
            message_history=self.prepared.history,
            user_memory_context=self.memory,
            user_info=None,
            citation_mapping=dict(self.artifacts.citation_mapping),
            next_citation_num=self.artifacts.citation_processor.get_next_citation_number()
            + 100 * self.tool_context.index(call.tool_call_id),
            skip_search_query_expansion=self.artifacts.has_called_search_tool,
            chat_files=self.artifacts.chat_files,
            url_snippet_map=extract_url_snippet_map(self.artifacts.gathered_documents),
            inject_memories_in_prompt=self.inject_memories,
        )
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

    def _after_turn(self, result: TurnResult) -> None:
        self.reminders.after_tools(result.tool_results)
        self.artifacts.update_context(result.message, result.tool_results)
        self.display_turn += 1 + int(bool(result.message.thinking))

        if result.message.tool_calls and not result.turn.is_last:
            return
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

    def _on_complete(self, event: AgentEvent) -> None:
        if not isinstance(event, AgentEndEvent) or event.outcome not in (
            "complete",
            "limit",
        ):
            return
        check_cancelled()
        self.emitter.emit(
            Packet(
                placement=Placement(turn_index=max(0, self.display_turn - 1)),
                obj=OverallStop(type="stop"),
            )
        )
