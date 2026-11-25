import time
from collections.abc import Callable, Mapping
from functools import partial

from pydantic import JsonValue

from onyx.agents.agent_coordination import MAX_CHILD_DEPTH
from onyx.agents.models import (
    AgentState,
    CompactionCheckpoint,
    PreparedStep,
    ReleaseFailed,
    StepInput,
    StepResult,
    ToolCallContext,
    ToolResultAmendment,
    ToolResultContext,
)
from onyx.agents.runtime import Agent, RestorableFeature
from onyx.chat.citation_processor import DynamicCitationProcessor
from onyx.chat.citation_utils import (
    build_context_file_citation_mapping,
    message_citation_sources,
    remap_received_citations,
)
from onyx.chat.errors import build_empty_llm_response_error
from onyx.chat.files import build_python_chat_files_from_search_docs
from onyx.chat.models import (
    ChatFeatureState,
    ChatMessageMetadata,
    ChatTurnSetup,
    CitationMode,
    PersonaPromptConfig,
    PromptMetadata,
    StagedChatFiles,
)
from onyx.chat.prompt_utils import (
    build_chat_prompt,
    callable_tools,
    prepare_prompt,
)
from onyx.chat.tool_results import (
    merged_chat_files,
    staged_result_details,
    tool_result_parts,
    tool_result_sources,
)
from onyx.configs.chat_configs import (
    CODE_MODE_ENABLED,
    CODE_MODE_MAX_LLM_CYCLES,
    MAX_LLM_CYCLES,
)
from onyx.context.models import UserMemoryContext
from onyx.file_store.models import ExtractedContextFiles, FileToolMetadata
from onyx.llm.interfaces import LLM, GenerationContext, LLMUserIdentity
from onyx.llm.model_request import estimate_text_tokens
from onyx.llm.models import (
    AssistantMessage,
    GenerationOptions,
    Message,
    NamedToolChoice,
    ReasoningEffort,
    ToolChoiceOptions,
    ToolResult,
    ToolResultMessage,
    UserMessage,
)
from onyx.prompts.chat_prompts import (
    ADDITIONAL_CONTEXT_PROMPT,
    ROOT_AGENT_IMPLICIT_WAIT_INSTRUCTIONS,
    ROOT_AGENT_INSTRUCTIONS,
    SUBAGENT_INSTRUCTIONS,
)
from onyx.tools.constants import PYTHON_TOOL_NAME
from onyx.tools.file_snapshot import SavedChatFile, SavedContextFiles
from onyx.tools.interface import Tool
from onyx.tools.models import ChatFile, ToolContext, ToolPreference
from onyx.tools.ordering import tool_order
from onyx.tools.tool_implementations.code_mode.code_mode_tool import (
    CodeModeTool,
    WaitCodeTool,
    with_code_mode,
)
from onyx.tools.tool_implementations.code_mode.prompt import (
    OTHER_OPERATION_MESSAGE,
    PROGRAM_FUNCTION_USE,
    RUN_USE,
    TOOL_USE,
    WAIT_USE,
)
from onyx.tools.tool_implementations.code_mode.shapes import (
    CODE_MODE_SHAPES,
    RUN_TOOL_NAMES,
    WAIT_TOOL_NAMES,
)
from onyx.tools.tool_implementations.open_url.open_url_tool import (
    OPEN_URL_TOOL_NAMES,
)
from onyx.tools.tool_implementations.question.question_tool import QuestionTool
from onyx.tools.tool_implementations.question.shapes import (
    QUESTION_SHAPES,
    QUESTION_TOOL_NAMES,
    QuestionShape,
)
from onyx.tools.tool_implementations.sandbox.sandbox_tools import SandboxTool
from onyx.tools.tool_implementations.sandbox.shapes import (
    SHELL_TOOL_NAMES,
)
from onyx.tools.tool_implementations.sandbox.spill import spill_large_result
from onyx.tools.tool_implementations.sandbox.turn import SandboxTurn
from onyx.tools.tool_implementations.search.models import SearchContext
from onyx.tools.tool_implementations.search.search_tool import (
    SearchTool,
    update_search_context,
)
from onyx.tools.tool_implementations.skills.skill_tools import (
    SKILLS_READ_TOOL_NAMES,
    skills_catalog_message,
)
from onyx.tools.tool_implementations.subagents.shapes import (
    AGENT_SHAPES,
    SPAWN_TOOL_NAMES,
    WAIT_AGENT_TOOL_NAMES,
)
from onyx.tools.tool_implementations.subagents.subagent_tools import (
    InterruptAgentTool,
    ListAgentsTool,
    SendMessageTool,
    SpawnAgentTool,
    WaitAgentTool,
)
from onyx.tools.tool_implementations.web_search.utils import extract_url_snippet_map
from onyx.tracing.flows import LLMFlow


def _offered_preference(
    preference: ToolPreference | None, tools: list[Tool]
) -> ToolPreference | None:
    # A run saved before tool options can prefer an old MCP or custom tool id.
    if preference is None or not any(tool.matches(preference) for tool in tools):
        return None
    return preference


class ChatAgent(Agent, RestorableFeature):
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
        preferred_tool: ToolPreference | None = None,
        user_identity: LLMUserIdentity | None = None,
        chat_files: list[ChatFile] | None = None,
        reasoning_effort: ReasoningEffort = ReasoningEffort.AUTO,
        include_citations: bool = True,
        all_injected_file_metadata: dict[str, FileToolMetadata] | None = None,
        inject_memories_in_prompt: bool = True,
        reminders_enabled: bool = True,
        checkpoint: CompactionCheckpoint | None = None,
        previous_run_id: str | None = None,
        agent_id: str | None = None,
        additional_context: str | None = None,
        code_mode: bool = False,
        is_subagent: bool = False,
        create_subagent: Callable[[], Agent] | None = None,
        can_spawn: bool = True,
        on_drained: Callable[[], None] | None = None,
        question_tool: Callable[[QuestionShape], QuestionTool] | None = None,
    ) -> None:
        """`on_drained`: see Agent; a root agent's runs end per-run tool state
        there (subagents share the root's tools and pass none). Only a root
        agent gets a question tool: `question_tool` builds it in the given
        shape. The model's tool family (LLMConfig.tool_family) selects the
        shapes of the code mode tools, the agent tools and the question tool."""
        tool_family = llm.config.tool_family
        agent_shape = AGENT_SHAPES[tool_family]
        # The fixed system block for the agent's role: a subagent, or a root
        # that can start agents.
        self.agent_instructions: str | None = None
        if is_subagent:
            self.agent_instructions = SUBAGENT_INSTRUCTIONS
        elif create_subagent is not None:
            self.agent_instructions = (
                ROOT_AGENT_IMPLICIT_WAIT_INSTRUCTIONS
                if agent_shape.wait_name is None
                else ROOT_AGENT_INSTRUCTIONS.format(name=agent_shape.wait_name)
            )
        self.custom_agent_prompt = custom_agent_prompt
        self.additional_context = additional_context
        self.context_files = context_files.model_copy(deep=True)
        self.file_metadata = all_injected_file_metadata
        # The tools the chat is configured with; restored and child agents receive
        # them, and code mode applies per agent.
        self.configured_tools = list(tools)
        self.code_mode = code_mode
        # Each agent instance has its own cells, so a restored run has none open;
        # a later run of this instance reopens them at its first step.
        self.application_tools, self.code_cells = (
            with_code_mode(self.configured_tools, CODE_MODE_SHAPES[tool_family])
            if code_mode
            else (list(self.configured_tools), None)
        )
        code_tool = next(
            (t for t in self.application_tools if isinstance(t, CodeModeTool)), None
        )
        # The name that the model calls a tool by: in code mode, its program
        # function's.
        self.called_name: Callable[[str], str] = (
            str if code_tool is None else code_tool.called_name
        )
        self.skills_catalog_message = skills_catalog_message(
            self.configured_tools, llm.config.max_input_tokens, self.called_name
        )
        # Programs batch tool calls, so code mode gets its own cap when it applies.
        self.max_steps = (
            CODE_MODE_MAX_LLM_CYCLES if self.code_cells is not None else MAX_LLM_CYCLES
        )
        self.include_citations = include_citations
        self.reasoning_effort = reasoning_effort
        self.memory = user_memory_context
        self.inject_memories = inject_memories_in_prompt
        self.search_context = SearchContext()
        self.started = time.monotonic()
        self.preferred_tool = _offered_preference(preferred_tool, self.configured_tools)
        self.chat_files = list(chat_files or [])
        # Restored agents and subagents receive the configured tools, so the
        # sandbox tools give each of them the chat's sandbox turn.
        self._sandbox_turn = next(
            (
                tool.turn
                for tool in self.configured_tools
                if isinstance(tool, SandboxTool)
            ),
            None,
        )
        # Only the Python tool reads the files of found documents; a sandbox
        # chat copies them into the VM instead.
        self.stages_files = self._sandbox_turn is None and any(
            tool.name == PYTHON_TOOL_NAME for tool in self.configured_tools
        )
        self.citation_processor = DynamicCitationProcessor(
            citation_mode=CitationMode.HYPERLINK
            if include_citations
            else CitationMode.REMOVE
        )
        # History owns existing numbers; adding or reordering project files must not reuse them.
        for message in messages:
            self.citation_processor.update_citation_mapping(
                message_citation_sources(message),
                update_duplicate_keys=isinstance(message, AssistantMessage),
            )
        self.initial_citations = build_context_file_citation_mapping(
            context_files.file_metadata, self.citation_processor.citation_to_doc
        )
        self.citation_processor.update_citation_mapping(
            self.initial_citations, update_duplicate_keys=True
        )
        self.gathered_documents = list(self.initial_citations.values())
        self.citation_mapping = {
            number: doc.document_id
            for number, doc in self.citation_processor.citation_to_doc.items()
        }
        self.has_called_search_tool = False
        self.persona = persona
        self.base_system_prompt = base_system_prompt
        self.reminders_enabled = reminders_enabled

        if create_subagent is not None:
            # A new list: code mode can return the configured tools themselves.
            # An agent at the nesting limit keeps the tools that reach existing agents.
            self.application_tools = [
                *self.application_tools,
                *(
                    [
                        SpawnAgentTool(
                            create_subagent, agent_shape, max_steps=self.max_steps
                        )
                    ]
                    if can_spawn
                    else []
                ),
                ListAgentsTool(),
                InterruptAgentTool(),
                SendMessageTool(agent_shape, max_steps=self.max_steps),
                # Subagents wait for their children before they finish.
                *(
                    []
                    if is_subagent or agent_shape.wait_name is None
                    else [
                        WaitAgentTool(
                            agent_shape,
                            open_cell_wait_name=lambda: (
                                self.code_cells.shape.wait_name
                                if self.code_cells is not None
                                and self.code_cells.has_open
                                else None
                            ),
                        )
                    ]
                ),
            ]
        if question_tool is not None and not is_subagent:
            self.application_tools = [
                *self.application_tools,
                question_tool(QUESTION_SHAPES[tool_family]),
            ]
        # A call of a tool that the agent does not offer can say what to call
        # instead (_unknown_tool_hint).
        self._code_tool = code_tool
        operation_uses: dict[str, str] = {}
        if code_tool is not None:
            code_shape = code_tool.shape
            # The program search exists only with deferred functions.
            search = code_shape.search if code_tool.has_search else None
            describe = code_shape.describe or search
            operation_uses |= dict.fromkeys(
                RUN_TOOL_NAMES, RUN_USE.format(run=code_shape.run_name)
            )
            operation_uses |= dict.fromkeys(
                WAIT_TOOL_NAMES, WAIT_USE.format(wait=code_shape.wait_name)
            )
            operation_uses |= {
                function.name: PROGRAM_FUNCTION_USE.format(
                    function=use.name, arguments="...", run=code_shape.run_name
                )
                for shape in CODE_MODE_SHAPES.values()
                for function, use in (
                    (shape.search, search),
                    (shape.describe, describe),
                )
                if function is not None and use is not None
            }
        # The code mode tools and program functions of every shape.
        self._code_mode_operation_messages = {
            name: OTHER_OPERATION_MESSAGE.format(name=name, use=use)
            for name, use in operation_uses.items()
        }
        offered = {tool.name for tool in self.application_tools} | {
            tool.name for tool in (code_tool.inner_tools if code_tool else [])
        }
        # The offered tool for each of its names in the other tool families'
        # shapes.
        self._own_names: dict[str, str] = {}
        for names in (
            SHELL_TOOL_NAMES,
            SPAWN_TOOL_NAMES,
            WAIT_AGENT_TOOL_NAMES,
            SKILLS_READ_TOOL_NAMES,
            OPEN_URL_TOOL_NAMES,
            QUESTION_TOOL_NAMES,
        ):
            own = next((name for name in names if name in offered), None)
            if own is not None:
                self._own_names |= dict.fromkeys(names - {own}, own)
        # The model reads the tools in tool order, whatever order the
        # configuration, code mode and the agent tools add them in.
        self.application_tools = sorted(self.application_tools, key=tool_order)
        # The root agent's sandbox and code mode results end with the file
        # copy status line when it changed. Subagents and the calls inside a
        # code mode program never read it, so they cannot use it up.
        self._file_status_tools = (
            frozenset(
                tool.name
                for tool in self.application_tools
                if isinstance(tool, (SandboxTool, CodeModeTool, WaitCodeTool))
            )
            if self._sandbox_turn is not None and not is_subagent
            else frozenset()
        )
        super().__init__(
            llm,
            tools=[tool.bind(self._tool_context) for tool in self.application_tools],
            agent_id=agent_id,
            previous_run_id=previous_run_id,
            state=AgentState(
                messages=messages,
                checkpoint=checkpoint,
            ),
            restoration=self,
            prepare_step=self._prepare_step,
            after_step=self._after_step,
            generation_context=GenerationContext(
                flow=LLMFlow.CHAT_RESPONSE, user_identity=user_identity
            ),
            after_tool_call=self._finalize_tool,
            # In a chat with a sandbox, large results go to a file in the VM.
            prepare_tool_result=partial(
                self._prepare_sandbox_result, self._sandbox_turn
            )
            if self._sandbox_turn is not None
            else None,
            unknown_tool_hint=self._unknown_tool_hint,
            on_finish=None if self.code_cells is None else self._finished_cells,
            on_suspend=None if self.code_cells is None else self._suspended_cells,
            on_drained=on_drained,
        )

    def _unknown_tool_hint(self, name: str) -> str | None:
        """What a call of `name`, a tool that the agent does not offer, says
        to call instead: a program function from a program, the agent's own
        name for another tool family's tool, or this shape's code mode
        operation."""
        own = self._own_names.get(name)
        if self._code_tool is not None:
            hint = self._code_tool.inner_call_hint(name, own)
            if hint is not None:
                return hint
        if own is not None:
            return OTHER_OPERATION_MESSAGE.format(
                name=name, use=TOOL_USE.format(name=own)
            )
        return self._code_mode_operation_messages.get(name)

    @property
    def code_mode_run_name(self) -> str | None:
        """The code mode run tool's name; None without code mode."""
        return None if self.code_cells is None else self.code_cells.shape.run_name

    def _prepare_sandbox_result(
        self, turn: SandboxTurn, context: ToolResultContext
    ) -> ToolResult:
        """Spill a large result, then add the file copy status line to a
        successful result that the root model gets. An amendment or a failed
        result gets no status line; the line waits for the next result."""
        result = spill_large_result(
            turn,
            context,
            shell_name=self.called_name(turn.shell.name),
            code_mode_run_name=self.code_mode_run_name,
        )
        if (
            context.amended
            or result.is_error
            or not any(call.name in self._file_status_tools for call in context.calls)
        ):
            return result
        line = None if turn.file_copies is None else turn.file_copies.status.line()
        if line is None:
            return result
        return result.model_copy(
            update={"content": f"{result.content}\n\n{line}", "estimated_tokens": None}
        )

    def capture_state(self) -> ChatFeatureState:
        return ChatFeatureState(
            persona=self.persona,
            context_files=SavedContextFiles.capture(self.context_files),
            file_metadata=self.file_metadata,
            memory=self.memory,
            reasoning_effort=self.reasoning_effort,
            include_citations=self.include_citations,
            inject_memories=self.inject_memories,
            preferred_tool=self.preferred_tool,
            code_mode=self.code_mode,
            base_prompt=self.base_system_prompt,
            custom_prompt=self.custom_agent_prompt,
            request_context=self.additional_context,
            reminders_enabled=self.reminders_enabled,
            elapsed_seconds=max(0.0, time.monotonic() - self.started),
            citation_sources=self.citation_processor.citation_to_doc,
            citation_mapping=self.citation_mapping,
            gathered_documents=self.gathered_documents,
            chat_files=[SavedChatFile.capture(file) for file in self.chat_files],
            has_called_search_tool=self.has_called_search_tool,
            search_context=self.search_context,
            code_cells=self.code_cells.saved() if self.code_cells is not None else [],
        )

    def restore_state(self, state: Mapping[str, JsonValue]) -> None:
        saved = ChatFeatureState.model_validate(state)
        if (
            saved.persona != self.persona
            or saved.context_files != SavedContextFiles.capture(self.context_files)
            or saved.file_metadata != self.file_metadata
            or saved.memory != self.memory
            or saved.reasoning_effort != self.reasoning_effort
            or saved.include_citations != self.include_citations
            or saved.inject_memories != self.inject_memories
            or _offered_preference(saved.preferred_tool, self.configured_tools)
            != self.preferred_tool
            or saved.code_mode != self.code_mode
            or saved.base_prompt != self.base_system_prompt
            or saved.custom_prompt != self.custom_agent_prompt
            or saved.request_context != self.additional_context
            or saved.reminders_enabled != self.reminders_enabled
        ):
            raise ValueError("Chat restoration configuration does not match")
        self.search_context = saved.search_context
        self.started = time.monotonic() - saved.elapsed_seconds
        self.citation_processor.citation_to_doc = saved.citation_sources
        self.citation_mapping = saved.citation_mapping
        self.gathered_documents = saved.gathered_documents
        self.chat_files = [file.restore() for file in saved.chat_files]
        self.has_called_search_tool = saved.has_called_search_tool
        if self.code_cells is not None:
            self.code_cells.restore(saved.code_cells)

    def _update_tool_context(self, responses: list[ToolResultMessage]) -> None:
        """Apply accepted tool results to the next request's context policy."""
        for response in responses:
            data = response.details
            if any(
                part.tool_name == SearchTool.NAME
                for part in tool_result_parts(response)
            ):
                self.has_called_search_tool = True
            sources = tool_result_sources(data)
            if sources is not None:
                self.gathered_documents.extend(sources.documents)
            if isinstance(data, StagedChatFiles):
                self.chat_files = merged_chat_files(self.chat_files, data.staged_files)
            if sources is None:
                continue
            self.citation_processor.update_citation_mapping(sources.citations)
            for number in sources.citations:
                if source := self.citation_processor.citation_to_doc.get(number):
                    self.citation_mapping[number] = source.document_id

    def _tool_context(self) -> ToolContext:
        """Read feature state that advances only after a completed step."""
        return ToolContext(
            search_context=self.search_context,
            user_memory_context=self.memory,
            citation_mapping=dict(self.citation_mapping),
            next_citation_num=self.citation_processor.get_next_citation_number(),
            skip_search_query_expansion=self.has_called_search_tool,
            chat_files=list(self.chat_files),
            url_snippet_map=extract_url_snippet_map(self.gathered_documents),
            called_name=self.called_name,
            inject_memories_in_prompt=self.inject_memories,
            python_stages_search_files=self.stages_files,
            sandbox_search_files=self._sandbox_turn.search_files.offer
            if self._sandbox_turn is not None
            else None,
        )

    def _prepare_step(self, state: StepInput) -> PreparedStep:
        previous = state.previous
        if previous is None:
            if self.code_cells is not None:
                self.code_cells.reopen()
            self.search_context = SearchContext()
            self.started = time.monotonic()
            self.gathered_documents = list(self.initial_citations.values())
            assistant = None
            for message in state.history:
                if isinstance(message, AssistantMessage):
                    assistant = message
                elif isinstance(message, ToolResultMessage) and assistant is not None:
                    self._update_tool_context([message])
            # Query expansion applies to the current turn only.
            self.has_called_search_tool = False
        received = remap_received_citations(
            state.received_inputs, self.citation_processor.citation_to_doc
        )
        if received.new_citations:
            known_documents = {
                document.document_id for document in self.gathered_documents
            }
            self.citation_processor.update_citation_mapping(received.new_citations)
            for number, document in received.new_citations.items():
                self.citation_mapping[number] = document.document_id
                if document.document_id not in known_documents:
                    known_documents.add(document.document_id)
                    self.gathered_documents.append(document)
        results = [
            message
            for message in state.messages
            if isinstance(message, ToolResultMessage)
        ]
        allowed_tool_names: frozenset[str] | None = None
        tool_choice = ToolChoiceOptions.AUTO
        available_tool_names = {
            tool.name for tool in callable_tools(self.application_tools)
        }
        if state.step.is_last:
            tool_choice = ToolChoiceOptions.NONE
            allowed_tool_names = frozenset()
            available_tool_names = set()
        prompt = build_chat_prompt(
            tools=self.application_tools,
            persona=self.persona,
            custom_prompt=self.custom_agent_prompt,
            base_prompt=self.base_system_prompt,
            files=self.context_files,
            memory=self.memory,
            inject_memories=self.inject_memories,
            reminders_enabled=self.reminders_enabled,
            results=results,
            previous_results=previous.tool_results if previous else [],
            is_last_step=state.step.is_last,
            has_history_citations=bool(self.citation_processor.citation_to_doc),
            preferred_tool=self.preferred_tool,
            called_name=self.called_name,
            code_mode_run_name=self.code_mode_run_name,
        )
        return PreparedStep(
            input_messages=received.messages,
            allowed_tool_names=allowed_tool_names,
            options=GenerationOptions(
                tool_choice=tool_choice, reasoning_effort=self.reasoning_effort
            ),
            output_metadata=ChatMessageMetadata(
                sources=dict(self.citation_processor.citation_to_doc),
                documents=list(self.gathered_documents),
                include_citations=self.include_citations,
                elapsed_seconds=time.monotonic() - self.started,
            ),
            assemble_messages=partial(
                prepare_prompt,
                agent_instructions=self.agent_instructions,
                system_prompt=prompt.system_prompt,
                user_info_prompt=prompt.user_info_prompt,
                skills_catalog_message=self.skills_catalog_message,
                custom_agent_prompt=prompt.custom_prompt,
                reminder_message=prompt.reminder,
                request_context_message=UserMessage(
                    content=ADDITIONAL_CONTEXT_PROMPT.format(
                        additional_context=self.additional_context
                    ),
                    metadata=PromptMetadata(is_reminder=True),
                )
                if self.additional_context
                else None,
                context_files=self.context_files,
                context_file_citations={
                    doc.document_id: number
                    for number, doc in self.initial_citations.items()
                },
                token_counter=estimate_text_tokens,
                all_injected_file_metadata=dict(self.file_metadata)
                if self.file_metadata
                else None,
                llm_config=self.llm.config,
                available_tool_names=available_tool_names,
            ),
        )

    def _after_step(self, result: StepResult) -> bool:
        self.search_context = update_search_context(
            self.search_context,
            [part for item in result.tool_results for part in tool_result_parts(item)],
        )
        self._update_tool_context(result.tool_results)
        if not result.message.tool_calls and not result.message.text:
            raise build_empty_llm_response_error(
                llm=self.llm,
                message=result.message,
                tool_choice=(
                    ToolChoiceOptions.REQUIRED
                    if isinstance(result.options.tool_choice, NamedToolChoice)
                    else result.options.tool_choice
                ),
            )
        return bool(result.message.tool_calls)

    def _finalize_tool(
        self, _context: ToolCallContext, result: ToolResult
    ) -> ToolResult:
        return self._staged(result)

    def _staged(self, result: ToolResult) -> ToolResult:
        """Stage the files of the result's documents for the Python tool."""
        if not self.stages_files:
            return result
        known = {file.file_id for file in self.chat_files if file.file_id is not None}
        result.details = staged_result_details(
            result.details, known, build_python_chat_files_from_search_docs
        )
        return result

    def _finished_cells(
        self, results: list[ToolResultMessage]
    ) -> list[ToolResultAmendment]:
        """Stop the response's open cells and save their final records."""
        if self.code_cells is None:
            return []
        return self._staged_release(partial(self.code_cells.finish, results))

    def _suspended_cells(
        self, results: list[ToolResultMessage]
    ) -> list[ToolResultAmendment]:
        """Close the response's cells when the run pauses, and save their final
        records; see CodeCells.suspend."""
        if self.code_cells is None:
            return []
        return self._staged_release(partial(self.code_cells.suspend, results))

    def _staged_release(
        self, release: Callable[[], list[ToolResultAmendment]]
    ) -> list[ToolResultAmendment]:
        try:
            return self._staged_amendments(release())
        except ReleaseFailed as failed:
            raise ReleaseFailed(
                failed.error, self._staged_amendments(failed.amendments)
            ) from failed.error

    def _staged_amendments(
        self, amendments: list[ToolResultAmendment]
    ) -> list[ToolResultAmendment]:
        return [
            amendment.model_copy(update={"result": self._staged(amendment.result)})
            for amendment in amendments
        ]


def build_chat_agent(
    state: AgentState,
    agent_id: str | None,
    previous_run_id: str | None,
    *,
    setup: ChatTurnSetup,
    llm: LLM,
    tools: list[Tool],
    inject_memories: bool,
    with_subagents: bool,
    preferred_tool: ToolPreference | None = None,
    additional_context: str | None = None,
    is_subagent: bool = False,
    depth: int = 0,
    on_drained: Callable[[], None] | None = None,
    question_tool: Callable[[QuestionShape], QuestionTool] | None = None,
) -> ChatAgent:
    """Build a chat conversation independently of the current root's feature.

    `with_subagents` adds the agent tools. Only callers that deliver follow-up
    responses, such as the web chat, enable them. `depth` counts levels below
    the root; an agent at `MAX_CHILD_DEPTH` cannot start agents.
    """
    return ChatAgent(
        create_subagent=chat_subagent_factory(
            setup=setup,
            llm=llm,
            tools=tools,
            inject_memories=inject_memories,
            depth=depth + 1,
        )
        if with_subagents
        else None,
        can_spawn=depth < MAX_CHILD_DEPTH,
        agent_id=agent_id,
        is_subagent=is_subagent,
        messages=state.messages,
        checkpoint=state.checkpoint,
        previous_run_id=previous_run_id,
        tools=tools,
        code_mode=CODE_MODE_ENABLED,
        custom_agent_prompt=setup.custom_agent_prompt,
        additional_context=additional_context,
        context_files=setup.extracted_context_files,
        persona=setup.persona,
        base_system_prompt=setup.base_system_prompt,
        user_memory_context=setup.user_memory_context,
        llm=llm,
        preferred_tool=preferred_tool,
        user_identity=setup.user_identity,
        chat_files=setup.chat_files_for_tools,
        reasoning_effort=setup.reasoning_effort,
        include_citations=setup.new_msg_req.include_citations,
        all_injected_file_metadata=setup.all_injected_file_metadata,
        inject_memories_in_prompt=inject_memories,
        on_drained=on_drained,
        question_tool=question_tool,
    )


def chat_subagent_factory(
    *,
    setup: ChatTurnSetup,
    llm: LLM,
    tools: list[Tool],
    inject_memories: bool,
    depth: int,
) -> Callable[[], ChatAgent]:
    """Build children at `depth` as saved children are restored; children can start children."""
    return partial(
        build_chat_agent,
        AgentState(),
        None,
        None,
        setup=setup,
        llm=llm,
        tools=tools,
        inject_memories=inject_memories,
        with_subagents=True,
        is_subagent=True,
        depth=depth,
    )
