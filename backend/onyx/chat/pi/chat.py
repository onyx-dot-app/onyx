import json
import time
from collections.abc import Callable
from typing import Any

from onyx.chat.chat_state import ChatStateContainer
from onyx.chat.chat_utils import build_python_chat_files_from_search_docs
from onyx.chat.citation_processor import (
    CitationMapping,
    CitationMode,
    DynamicCitationProcessor,
)
from onyx.chat.citation_utils import update_citation_processor_from_tool_response
from onyx.chat.emitter import Emitter
from onyx.chat.errors import build_empty_llm_response_error
from onyx.chat.llm_step import translate_history_to_llm_format
from onyx.chat.message_history import (
    build_context_file_citation_mapping,
    construct_message_history,
    select_reminder_text,
)
from onyx.chat.models import (
    ChatMessageSimple,
    ExtractedContextFiles,
    FileToolMetadata,
    LlmStepResult,
    ToolCallSimple,
)
from onyx.chat.pi.host_state import (
    ChatFileSnapshot,
    ChatHostSnapshot,
    ChatMessageSnapshot,
    ChatStateSnapshot,
    CitationSnapshot,
)
from onyx.chat.pi.models import PiToolCall, PiToolResult
from onyx.chat.pi.presentation import ChatPresentation
from onyx.chat.pi.prompts import ChatInstructions
from onyx.chat.pi.tool_results import persist_tool_result
from onyx.chat.prompt_utils import (
    get_default_base_system_prompt,
)
from onyx.configs.app_configs import INTEGRATION_TESTS_MODE
from onyx.configs.chat_configs import MAX_LLM_CYCLES
from onyx.configs.constants import MessageType
from onyx.configs.model_configs import GEN_AI_INPUT_TOKEN_SAFETY_MARGIN
from onyx.context.search.models import SearchDoc, SearchDocsResponse
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.memory import UserMemoryContext
from onyx.db.models import Persona
from onyx.llm.interfaces import LLM, LLMUserIdentity, ToolChoiceOptions
from onyx.llm.model_response import ModelResponseStream
from onyx.llm.models import FunctionCall, ReasoningEffort, ToolCall
from onyx.llm.request_context import get_llm_request_params
from onyx.llm.utils import model_supports_image_input
from onyx.server.query_and_chat.placement import Placement
from onyx.server.query_and_chat.streaming_models import (
    Packet,
    ToolCallDebug,
    TopLevelBranching,
)
from onyx.tools.built_in_tools import CITEABLE_TOOLS_NAMES, STOPPING_TOOLS_NAMES
from onyx.tools.interface import Tool
from onyx.tools.models import (
    ChatFile,
    CustomToolCallSummary,
    CustomToolUserFileSnapshot,
    PythonToolRichResponse,
    ToolCallInfo,
    ToolResponse,
)
from onyx.tools.tool_implementations.images.models import FinalImageGenerationResponse
from onyx.tools.tool_implementations.open_url.open_url_tool import OpenURLTool
from onyx.tools.tool_implementations.python.python_tool import PythonTool
from onyx.tools.tool_implementations.search.search_tool import SearchTool
from onyx.tools.tool_implementations.web_search.utils import extract_url_snippet_map
from onyx.tools.tool_implementations.web_search.web_search_tool import WebSearchTool
from onyx.tools.tool_runner import run_tool_calls
from onyx.tools.utils import compute_all_tool_tokens
from onyx.tracing.flows import LLMFlow
from onyx.tracing.llm_utils import record_llm_span_output, traced_llm_call


class ChatHost:
    """Onyx context, tool effects and presentation for one Pi-owned run."""

    def __init__(
        self,
        emitter: Emitter,
        state_container: ChatStateContainer,
        simple_chat_history: list[ChatMessageSimple],
        tools: list[Tool],
        custom_agent_prompt: str | None,
        context_files: ExtractedContextFiles,
        persona: Persona | None,
        user_memory_context: UserMemoryContext | None,
        llm: LLM,
        token_counter: Callable[[str], int],
        forced_tool_id: int | None = None,
        user_identity: LLMUserIdentity | None = None,
        chat_session_id: str | None = None,
        chat_files: list[ChatFile] | None = None,
        reasoning_effort: ReasoningEffort = ReasoningEffort.AUTO,
        include_citations: bool = True,
        all_injected_file_metadata: dict[str, FileToolMetadata] | None = None,
        inject_memories_in_prompt: bool = True,
        base_prompt: str | None = None,
    ) -> None:
        self.emitter = emitter
        self.state_container = state_container
        self.simple_chat_history = simple_chat_history
        self.tools = tools
        self.context_files = context_files
        self.user_memory_context = user_memory_context
        self.llm = llm
        self.token_counter = token_counter
        self.forced_tool_id = forced_tool_id
        self.user_identity = user_identity
        self.chat_session_id = chat_session_id
        self.reasoning_effort = reasoning_effort
        self.include_citations = include_citations
        self.all_injected_file_metadata = all_injected_file_metadata
        self.inject_memories_in_prompt = inject_memories_in_prompt
        self.chat_files: list[ChatFile] = list(chat_files or [])
        self.initial_chat_file_names = {file.filename for file in self.chat_files}
        self.started_at = time.time()
        self.presenter: ChatPresentation | None = None
        self.citation_processor = DynamicCitationProcessor(
            citation_mode=CitationMode.HYPERLINK
            if self.include_citations
            else CitationMode.REMOVE
        )
        self.project_citation_mapping: CitationMapping = {}
        if self.context_files.file_metadata:
            self.project_citation_mapping = build_context_file_citation_mapping(
                self.context_files.file_metadata
            )
            self.citation_processor.update_citation_mapping(
                self.project_citation_mapping
            )
        self.llm_step_result = LlmStepResult(
            reasoning=None,
            answer=None,
            tool_calls=None,
            raw_answer=None,
            finish_reason=None,
        )
        self.available_tokens = int(
            self.llm.config.max_input_tokens * (1 - GEN_AI_INPUT_TOKEN_SAFETY_MARGIN)
        )
        self.image_files_replayed_as_markers = any(
            (
                msg.message_type == MessageType.USER and msg.image_files
                for msg in self.simple_chat_history
            )
        ) and (
            not model_supports_image_input(
                self.llm.config.model_name,
                self.llm.config.model_provider,
                self.llm.config.deployment_name,
            )
        )
        self.tool_choice: ToolChoiceOptions = ToolChoiceOptions.AUTO
        self.gathered_documents: list[SearchDoc] | None = (
            list(self.project_citation_mapping.values())
            if self.project_citation_mapping
            else None
        )
        self.always_cite_documents: bool = bool(
            self.context_files.use_as_search_filter or self.context_files.file_texts
        )
        self.should_cite_documents: bool = False
        self.ran_image_gen: bool = False
        self.just_ran_web_search: bool = False
        self.has_open_url_tool: bool = any(
            (isinstance(tool, OpenURLTool) for tool in self.tools)
        )
        self.has_called_search_tool: bool = False
        self.code_interpreter_file_generated: bool = False
        self.citation_mapping: dict[int, str] = {}
        if base_prompt is None:
            with get_session_with_current_tenant() as db_session:
                base_prompt = get_default_base_system_prompt(db_session)
        self.instructions = ChatInstructions(
            base_prompt=base_prompt,
            custom_prompt=custom_agent_prompt,
            persona=persona,
            memory=user_memory_context,
            include_memories=inject_memories_in_prompt,
            tools=tools,
            token_counter=token_counter,
        )
        self.reasoning_cycles = 0
        self.llm_cycle_count = 0
        self.final_tools: list[Tool] = []
        self.truncated_message_history: list[ChatMessageSimple] = []
        self.tool_defs: list[dict] = []

    def prepare_step(self, cycle: int) -> dict[str, Any]:
        self.llm_cycle_count = cycle
        out_of_cycles = self.llm_cycle_count == MAX_LLM_CYCLES - 1
        if self.forced_tool_id:
            self.final_tools = [
                tool for tool in self.tools if tool.id == self.forced_tool_id
            ]
            if not self.final_tools:
                raise ValueError(f"Tool {self.forced_tool_id} not found in tools")
            self.tool_choice = ToolChoiceOptions.REQUIRED
            self.forced_tool_id = None
        elif out_of_cycles or self.ran_image_gen:
            self.tool_choice = ToolChoiceOptions.NONE
            self.final_tools = []
        else:
            self.tool_choice = ToolChoiceOptions.AUTO
            self.final_tools = self.tools
        system_prompt, custom_prompt, task_prompt = self.instructions.build(
            cite=self.should_cite_documents or self.always_cite_documents,
        )
        reminder_message_text = select_reminder_text(
            ran_image_gen=self.ran_image_gen,
            just_ran_web_search=self.just_ran_web_search,
            has_open_url_tool=self.has_open_url_tool,
            out_of_cycles=out_of_cycles,
            persona_task_prompt=task_prompt,
            include_citation_reminder=self.should_cite_documents
            or self.always_cite_documents,
            include_file_reminder=self.code_interpreter_file_generated,
        )
        reminder_msg = (
            ChatMessageSimple(
                message=reminder_message_text,
                token_count=self.token_counter(reminder_message_text),
                message_type=MessageType.USER_REMINDER,
            )
            if reminder_message_text
            else None
        )
        tool_token_budget = compute_all_tool_tokens(
            self.final_tools, self.token_counter
        )
        self.truncated_message_history = construct_message_history(
            system_prompt=system_prompt,
            custom_agent_prompt=custom_prompt,
            simple_chat_history=self.simple_chat_history,
            reminder_message=reminder_msg,
            context_files=self.context_files,
            available_tokens=max(0, self.available_tokens - tool_token_budget),
            token_counter=self.token_counter,
            all_injected_file_metadata=self.all_injected_file_metadata,
            image_files_replayed_as_markers=self.image_files_replayed_as_markers,
        )
        self.tool_defs = [tool.tool_definition() for tool in self.final_tools]
        translated = translate_history_to_llm_format(
            self.truncated_message_history, self.llm.config, native_tool_messages=True
        )
        messages = translated if isinstance(translated, list) else [translated]
        return {
            "history": [
                message.model_dump(mode="json", exclude_none=True)
                for message in messages
            ],
            "tools": self.tool_defs,
            "toolChoice": self.tool_choice.value,
        }

    def feed_step(
        self, chunks: list[ModelResponseStream], *, finish: bool = False
    ) -> None:
        """Project a bounded batch; no live generator survives the callback."""
        if self.presenter is None:
            self.presenter = ChatPresentation(
                self.emitter,
                self.state_container,
                self.citation_processor,
                self.llm_cycle_count + self.reasoning_cycles,
                self.gathered_documents,
                max(0.0, time.time() - self.started_at),
            )
            self.state_container.set_request_params(get_llm_request_params())
        presenter = self.presenter
        for chunk in chunks:
            presenter.feed(chunk)
        if not finish:
            return
        self.llm_step_result = presenter.finish()
        with traced_llm_call(
            flow=LLMFlow.CHAT_RESPONSE,
            model=self.llm.config.model_name,
            provider=self.llm.config.model_provider,
            extra_config={"agent_sdk": "pi"},
            input_messages=translate_history_to_llm_format(
                self.truncated_message_history,
                self.llm.config,
                native_tool_messages=True,
            ),
            tools=self.tool_defs,
        ) as span:
            record_llm_span_output(
                span,
                presenter.answer,
                usage=presenter.usage,
                reasoning=presenter.reasoning,
                tool_calls=[
                    ToolCall(
                        id=call.tool_call_id,
                        function=FunctionCall(
                            name=call.tool_name,
                            arguments=json.dumps(call.tool_args),
                        ),
                    )
                    for call in presenter.calls
                ],
            )
        if presenter.usage:
            self.llm.record_usage(presenter.usage)
        self.reasoning_cycles += presenter.reasoning_sections
        self.presenter = None

    def snapshot(self) -> ChatHostSnapshot:
        return ChatHostSnapshot(
            state=ChatStateSnapshot.capture(self.state_container),
            citations=CitationSnapshot.capture(self.citation_processor),
            presentation=self.presenter.snapshot() if self.presenter else None,
            simple_chat_history=[
                ChatMessageSnapshot.capture(message)
                for message in self.simple_chat_history
            ],
            chat_files=[
                ChatFileSnapshot.capture(file)
                for file in self.chat_files
                if file.filename not in self.initial_chat_file_names
            ],
            started_at=self.started_at,
            forced_tool_id=self.forced_tool_id,
            llm_step_result=self.llm_step_result,
            tool_choice=self.tool_choice,
            gathered_documents=self.gathered_documents,
            should_cite_documents=self.should_cite_documents,
            ran_image_gen=self.ran_image_gen,
            just_ran_web_search=self.just_ran_web_search,
            has_called_search_tool=self.has_called_search_tool,
            code_interpreter_file_generated=self.code_interpreter_file_generated,
            citation_mapping=self.citation_mapping,
            reasoning_cycles=self.reasoning_cycles,
            llm_cycle_count=self.llm_cycle_count,
            final_tool_ids=[tool.id for tool in self.final_tools],
            truncated_message_history=[
                ChatMessageSnapshot.capture(message)
                for message in self.truncated_message_history
            ],
            tool_defs=self.tool_defs,
        )

    def restore(self, snapshot: ChatHostSnapshot) -> None:
        snapshot.state.restore(self.state_container)
        self.citation_processor = snapshot.citations.restore()
        self.presenter = (
            ChatPresentation.restore(
                snapshot.presentation,
                self.emitter,
                self.state_container,
                self.citation_processor,
            )
            if snapshot.presentation
            else None
        )
        self.simple_chat_history = [
            message.restore() for message in snapshot.simple_chat_history
        ]
        self.chat_files = [
            file
            for file in self.chat_files
            if file.filename in self.initial_chat_file_names
        ] + [file.restore() for file in snapshot.chat_files]
        self.started_at = snapshot.started_at
        self.forced_tool_id = snapshot.forced_tool_id
        self.llm_step_result = snapshot.llm_step_result
        self.tool_choice = snapshot.tool_choice
        self.gathered_documents = snapshot.gathered_documents
        self.should_cite_documents = snapshot.should_cite_documents
        self.ran_image_gen = snapshot.ran_image_gen
        self.just_ran_web_search = snapshot.just_ran_web_search
        self.has_called_search_tool = snapshot.has_called_search_tool
        self.code_interpreter_file_generated = snapshot.code_interpreter_file_generated
        self.citation_mapping = snapshot.citation_mapping.copy()
        self.reasoning_cycles = snapshot.reasoning_cycles
        self.llm_cycle_count = snapshot.llm_cycle_count
        tools_by_id = {tool.id: tool for tool in self.tools}
        self.final_tools = [tools_by_id[tool_id] for tool_id in snapshot.final_tool_ids]
        self.truncated_message_history = [
            message.restore() for message in snapshot.truncated_message_history
        ]
        self.tool_defs = list(snapshot.tool_defs)

    def execute_tools(self, calls: list[PiToolCall]) -> dict[str, str]:
        self.state_container.set_citation_mapping(
            self.citation_processor.citation_to_doc
        )
        tool_responses: list[ToolResponse] = []
        requested = {call.id: call for call in calls}
        tool_calls = [
            # Pi normalizes arguments during schema validation (for example "2" -> 2).
            call.model_copy(
                update={"tool_args": requested[call.tool_call_id].arguments}
            )
            for call in self.llm_step_result.tool_calls or []
            if call.tool_call_id in requested
        ]
        if len(requested) != len(calls) or len(tool_calls) != len(calls):
            raise ValueError("Pi requested a tool call outside the current model step")
        for call in tool_calls:
            requested_call = requested[call.tool_call_id]
            if requested_call.name != call.tool_name or call.tool_name not in {
                tool.name for tool in self.final_tools
            }:
                raise ValueError(
                    "Pi requested a tool call that differs from the model step"
                )
        if INTEGRATION_TESTS_MODE and tool_calls:
            for tool_call in tool_calls:
                self.emitter.emit(
                    Packet(
                        placement=tool_call.placement,
                        obj=ToolCallDebug(
                            tool_call_id=tool_call.tool_call_id,
                            tool_name=tool_call.tool_name,
                            tool_args=tool_call.tool_args,
                        ),
                    )
                )
        if len(tool_calls) > 1:
            self.emitter.emit(
                Packet(
                    placement=Placement(turn_index=tool_calls[0].placement.turn_index),
                    obj=TopLevelBranching(num_parallel_branches=len(tool_calls)),
                )
            )
        self.just_ran_web_search = False
        parallel_tool_call_results = run_tool_calls(
            tool_calls=tool_calls,
            tools=self.final_tools,
            preserve_call_ids=True,
            execution_concurrency=4,
            message_history=self.truncated_message_history,
            user_memory_context=self.user_memory_context,
            user_info=None,
            citation_mapping=self.citation_mapping,
            next_citation_num=self.citation_processor.get_next_citation_number(),
            max_concurrent_tools=None,
            skip_search_query_expansion=self.has_called_search_tool,
            chat_files=self.chat_files,
            url_snippet_map=extract_url_snippet_map(self.gathered_documents or []),
            inject_memories_in_prompt=self.inject_memories_in_prompt,
        )
        tool_responses = parallel_tool_call_results.tool_responses
        self.citation_mapping = parallel_tool_call_results.updated_citation_mapping
        for tool_response in tool_responses:
            self.accept_tool_result(tool_response)
        if any(
            (
                tool.tool_name in STOPPING_TOOLS_NAMES
                for tool in self.llm_step_result.tool_calls or []
            )
        ):
            self.ran_image_gen = True
        if self.llm_step_result.tool_calls and any(
            (
                tool.tool_name in CITEABLE_TOOLS_NAMES
                for tool in self.llm_step_result.tool_calls or []
            )
        ):
            self.should_cite_documents = True
        return {
            response.tool_call.tool_call_id: response.llm_facing_response
            for response in tool_responses
            if response.tool_call is not None
        }

    def accept_tool_result(self, tool_response: ToolResponse) -> None:
        if tool_response.tool_call is None:
            raise ValueError("Tool response missing tool_call reference")
        tool_call = tool_response.tool_call
        tab_index = tool_call.placement.tab_index
        if tool_call.tool_name == SearchTool.NAME:
            self.has_called_search_tool = True
        if tool_call.tool_name == PythonTool.NAME and (
            not self.code_interpreter_file_generated
        ):
            try:
                parsed = json.loads(tool_response.llm_facing_response)
                if parsed.get("generated_files"):
                    self.code_interpreter_file_generated = True
            except (json.JSONDecodeError, AttributeError):
                pass
        tools_by_name = {tool.name: tool for tool in self.final_tools}
        tool = tools_by_name.get(tool_call.tool_name)
        if not tool:
            raise ValueError(f"Tool '{tool_call.tool_name}' not found in tools list")
        search_docs = None
        displayed_docs = None
        if isinstance(tool_response.rich_response, SearchDocsResponse):
            search_docs = tool_response.rich_response.search_docs
            displayed_docs = tool_response.rich_response.displayed_docs
            if search_docs:
                self.state_container.add_search_docs(search_docs)
            if self.gathered_documents:
                self.gathered_documents.extend(search_docs)
            else:
                self.gathered_documents = search_docs
            if search_docs and tool_call.tool_name == WebSearchTool.NAME:
                self.just_ran_web_search = True
            if search_docs:
                staged = build_python_chat_files_from_search_docs(
                    search_docs=search_docs
                )
                if staged:
                    existing_filenames = {cf.filename for cf in self.chat_files}
                    self.chat_files.extend(
                        (cf for cf in staged if cf.filename not in existing_filenames)
                    )
        generated_images = None
        if isinstance(tool_response.rich_response, FinalImageGenerationResponse):
            generated_images = tool_response.rich_response.generated_images
        generated_files = None
        if isinstance(tool_response.rich_response, PythonToolRichResponse):
            generated_files = tool_response.rich_response.generated_files or None
        generated_file_ids = None
        if isinstance(
            tool_response.rich_response, CustomToolCallSummary
        ) and isinstance(
            tool_response.rich_response.tool_result, CustomToolUserFileSnapshot
        ):
            generated_file_ids = (
                tool_response.rich_response.tool_result.file_ids or None
            )
        saved_response = persist_tool_result(tool_response, self.user_memory_context)
        tool_call_info = ToolCallInfo(
            parent_tool_call_id=None,
            turn_index=self.llm_cycle_count + self.reasoning_cycles,
            tab_index=tab_index,
            tool_name=tool_call.tool_name,
            tool_call_id=tool_call.tool_call_id,
            tool_id=tool.id,
            reasoning_tokens=self.llm_step_result.reasoning,
            tool_call_arguments=tool_call.tool_args,
            tool_call_response=saved_response,
            search_docs=displayed_docs or search_docs,
            generated_images=generated_images,
            generated_files=generated_files,
            generated_file_ids=generated_file_ids,
        )
        self.state_container.add_tool_call(tool_call_info)
        update_citation_processor_from_tool_response(
            tool_response, self.citation_processor
        )

    def record_turn(self, results: list[PiToolResult]) -> None:
        calls = {
            call.tool_call_id: call for call in self.llm_step_result.tool_calls or []
        }
        responses = [
            ToolResponse(
                tool_call=calls[result.tool_call_id],
                llm_facing_response="\n".join(block.text for block in result.content),
                rich_response=None,
            )
            for result in results
        ]
        self.append_tool_history(responses)

    def append_tool_history(self, tool_responses: list[ToolResponse]) -> None:
        valid_tool_responses = [tr for tr in tool_responses if tr.tool_call is not None]
        tool_calls_simple: list[ToolCallSimple] = []
        for tool_response in valid_tool_responses:
            tc = tool_response.tool_call
            assert tc is not None
            tool_call_message = tc.to_msg_str()
            tool_call_token_count = self.token_counter(tool_call_message)
            tool_calls_simple.append(
                ToolCallSimple(
                    tool_call_id=tc.tool_call_id,
                    tool_name=tc.tool_name,
                    tool_arguments=tc.tool_args,
                    token_count=tool_call_token_count,
                )
            )
        total_tool_call_tokens = (
            sum(tc.token_count for tc in tool_calls_simple)
            + self.token_counter(self.llm_step_result.reasoning or "")
            + self.token_counter(self.llm_step_result.raw_answer or "")
        )
        assistant_with_tools = ChatMessageSimple(
            message="",
            token_count=total_tool_call_tokens,
            message_type=MessageType.ASSISTANT,
            tool_calls=tool_calls_simple,
            image_files=None,
        )
        self.simple_chat_history.append(assistant_with_tools)
        for tool_response in valid_tool_responses:
            tc = tool_response.tool_call
            assert tc is not None
            tool_response_message = tool_response.llm_facing_response
            tool_response_token_count = self.token_counter(tool_response_message)
            tool_response_msg = ChatMessageSimple(
                message=tool_response_message,
                token_count=tool_response_token_count,
                message_type=MessageType.TOOL_CALL_RESPONSE,
                tool_call_id=tc.tool_call_id,
                image_files=None,
            )
            self.simple_chat_history.append(tool_response_msg)

    def validate_final_response(self) -> None:
        if not self.llm_step_result.answer and (not self.llm_step_result.tool_calls):
            raise build_empty_llm_response_error(
                llm=self.llm,
                llm_step_result=self.llm_step_result,
                tool_choice=self.tool_choice,
            )
        if not self.llm_step_result.answer:
            raise RuntimeError(
                "The LLM did not return a final answer after tool execution. Typically this indicates invalid tool-call output, a model/provider mismatch, or serving API misconfiguration."
            )
