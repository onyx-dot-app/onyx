"""Legacy in-process inference loop, selected with ONYX_CHAT_ENGINE=legacy."""

import json
import time
from collections.abc import Callable
from typing import Literal

from onyx.chat.chat_state import ChatStateContainer
from onyx.chat.chat_utils import (
    build_python_chat_files_from_search_docs,
    create_tool_call_failure_messages,
)
from onyx.chat.citation_processor import (
    CitationMapping,
    CitationMode,
    DynamicCitationProcessor,
)
from onyx.chat.citation_utils import update_citation_processor_from_tool_response
from onyx.chat.emitter import Emitter
from onyx.chat.errors import EmptyLLMResponseError as EmptyLLMResponseError
from onyx.chat.errors import (
    build_empty_llm_response_error as _build_empty_llm_response_error,
)
from onyx.chat.llm_step import (
    _looks_like_xml_tool_call_payload,
    extract_tool_calls_from_response_text,
    run_llm_step,
)
from onyx.chat.message_history import (
    build_context_file_citation_mapping as _build_context_file_citation_mapping,
)
from onyx.chat.message_history import (
    construct_message_history as construct_message_history,
)
from onyx.chat.message_history import (
    select_reminder_text as select_reminder_text,
)
from onyx.chat.models import (
    ChatMessageSimple,
    ExtractedContextFiles,
    FileToolMetadata,
    LlmStepResult,
    ToolCallSimple,
)
from onyx.chat.prompt_utils import (
    build_system_prompt,
    get_default_base_system_prompt,
    process_prompt_template,
)
from onyx.configs.app_configs import INTEGRATION_TESTS_MODE
from onyx.configs.chat_configs import MAX_LLM_CYCLES
from onyx.configs.constants import MessageType
from onyx.configs.model_configs import GEN_AI_INPUT_TOKEN_SAFETY_MARGIN
from onyx.context.search.models import SearchDoc, SearchDocsResponse
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.memory import UserMemoryContext, add_memory, update_memory_at_index
from onyx.db.models import Persona
from onyx.llm.interfaces import LLM, LLMUserIdentity, ToolChoiceOptions
from onyx.llm.models import ReasoningEffort
from onyx.llm.utils import model_supports_image_input
from onyx.prompts.prompt_utils import substitute_user_placeholders
from onyx.server.query_and_chat.placement import Placement
from onyx.server.query_and_chat.streaming_models import (
    OverallStop,
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
    MemoryToolResponseSnapshot,
    PythonToolRichResponse,
    ToolCallInfo,
    ToolCallKickoff,
    ToolResponse,
)
from onyx.tools.tool_implementations.images.models import FinalImageGenerationResponse
from onyx.tools.tool_implementations.memory.models import MemoryToolResponse
from onyx.tools.tool_implementations.open_url.open_url_tool import OpenURLTool
from onyx.tools.tool_implementations.python.python_tool import PythonTool
from onyx.tools.tool_implementations.search.search_tool import SearchTool
from onyx.tools.tool_implementations.web_search.utils import extract_url_snippet_map
from onyx.tools.tool_implementations.web_search.web_search_tool import WebSearchTool
from onyx.tools.tool_runner import run_tool_calls
from onyx.tools.utils import compute_all_tool_tokens
from onyx.tracing.framework.create import ChatTraceMetadata, trace
from onyx.utils.logger import setup_logger
from shared_configs.contextvars import get_current_incognito_record_mode

logger = setup_logger()


def _try_fallback_tool_extraction(
    llm_step_result: LlmStepResult,
    tool_choice: ToolChoiceOptions,
    fallback_extraction_attempted: bool,
    tool_defs: list[dict],
    turn_index: int,
) -> tuple[LlmStepResult, bool]:
    """Attempt to extract tool calls from response text as a fallback.

    This is a last resort fallback for low quality LLMs or those that don't have
    tool calling from the serving layer. Also triggers if there's reasoning but
    no answer and no tool calls.

    Args:
        llm_step_result: The result from the LLM step
        tool_choice: The tool choice option used for this step
        fallback_extraction_attempted: Whether fallback extraction was already attempted
        tool_defs: List of tool definitions
        turn_index: The current turn index for placement

    Returns:
        Tuple of (possibly updated LlmStepResult, whether fallback was attempted this call)
    """
    if fallback_extraction_attempted:
        return llm_step_result, False

    no_tool_calls = (
        not llm_step_result.tool_calls or len(llm_step_result.tool_calls) == 0
    )
    reasoning_but_no_answer_or_tools = (
        llm_step_result.reasoning and not llm_step_result.answer and no_tool_calls
    )
    xml_tool_call_text_detected = no_tool_calls and (
        _looks_like_xml_tool_call_payload(llm_step_result.answer)
        or _looks_like_xml_tool_call_payload(llm_step_result.raw_answer)
        or _looks_like_xml_tool_call_payload(llm_step_result.reasoning)
    )
    should_try_fallback = (
        (tool_choice == ToolChoiceOptions.REQUIRED and no_tool_calls)
        or reasoning_but_no_answer_or_tools
        or xml_tool_call_text_detected
    )

    if not should_try_fallback:
        return llm_step_result, False

    # Try to extract from answer first, then fall back to reasoning
    extracted_tool_calls: list[ToolCallKickoff] = []

    if llm_step_result.answer:
        extracted_tool_calls = extract_tool_calls_from_response_text(
            response_text=llm_step_result.answer,
            tool_definitions=tool_defs,
            placement=Placement(turn_index=turn_index),
        )
    if (
        not extracted_tool_calls
        and llm_step_result.raw_answer
        and llm_step_result.raw_answer != llm_step_result.answer
    ):
        extracted_tool_calls = extract_tool_calls_from_response_text(
            response_text=llm_step_result.raw_answer,
            tool_definitions=tool_defs,
            placement=Placement(turn_index=turn_index),
        )
    if not extracted_tool_calls and llm_step_result.reasoning:
        extracted_tool_calls = extract_tool_calls_from_response_text(
            response_text=llm_step_result.reasoning,
            tool_definitions=tool_defs,
            placement=Placement(turn_index=turn_index),
        )
    if extracted_tool_calls:
        logger.info(
            "Extracted %s tool call(s) from response text as fallback",
            len(extracted_tool_calls),
        )
        return (
            LlmStepResult(
                reasoning=llm_step_result.reasoning,
                answer=llm_step_result.answer,
                tool_calls=extracted_tool_calls,
                raw_answer=llm_step_result.raw_answer,
                finish_reason=llm_step_result.finish_reason,
            ),
            True,
        )

    return llm_step_result, True


# Default 6 covers the common search → open_url pattern:
# Cycle 1: Calls web_search for something
# Cycle 2: Calls open_url for some results
# Cycle 3: Calls web_search for some other aspect of the question
# Cycle 4: Calls open_url for some results
# Cycle 5: Maybe call open_url for some additional results or because last set failed
# Cycle 6: No more tools available, forced to answer
# Override via the MAX_LLM_CYCLES env var when running with tool-heavy MCPs
# that legitimately need more turns. Imported from chat_configs.


def run_llm_loop(
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
) -> None:
    with trace(
        "run_llm_loop",
        group_id=chat_session_id,
        metadata=ChatTraceMetadata(
            chat_session_id=chat_session_id,
            user_id=user_identity.user_id if user_identity else None,
        ).model_dump(),
    ):
        # Fix some LiteLLM issues,
        from onyx.llm.litellm_singleton.config import (
            initialize_litellm,
        )  # Here for lazy load LiteLLM

        initialize_litellm()

        # Normalize chat_files to a mutable list so we can extend it mid-loop
        # when a search hit carries an attached file the Python tool should
        # see.
        chat_files = list(chat_files or [])

        # Track when the loop starts for calculating time-to-answer
        loop_start_time = time.monotonic()

        # Initialize citation processor for handling citations dynamically
        # When include_citations is True, use HYPERLINK mode to format citations as [[1]](url)
        # When include_citations is False, use REMOVE mode to strip citations from output
        citation_processor = DynamicCitationProcessor(
            citation_mode=(
                CitationMode.HYPERLINK if include_citations else CitationMode.REMOVE
            )
        )

        # Add project file citation mappings if project files are present
        project_citation_mapping: CitationMapping = {}
        if context_files.file_metadata:
            project_citation_mapping = _build_context_file_citation_mapping(
                context_files.file_metadata
            )
            citation_processor.update_citation_mapping(project_citation_mapping)

        llm_step_result = LlmStepResult(
            reasoning=None,
            answer=None,
            tool_calls=None,
            raw_answer=None,
            finish_reason=None,
        )

        # Hold back a margin below max_input_tokens: our tiktoken estimate can
        # undercount the provider's tokenizer and overflow the context window.
        available_tokens = int(
            llm.config.max_input_tokens * (1 - GEN_AI_INPUT_TOKEN_SAFETY_MARGIN)
        )
        # When the model takes no image input, history images are replayed as
        # short text markers (translate_history_to_llm_format) — budget them
        # as markers too, not at their stored image token cost.
        image_files_replayed_as_markers = any(
            msg.message_type == MessageType.USER and msg.image_files
            for msg in simple_chat_history
        ) and not model_supports_image_input(
            llm.config.model_name, llm.config.model_provider, llm.config.deployment_name
        )
        tool_choice: ToolChoiceOptions = ToolChoiceOptions.AUTO
        # Initialize gathered_documents with project files if present
        gathered_documents: list[SearchDoc] | None = (
            list(project_citation_mapping.values())
            if project_citation_mapping
            else None
        )
        # TODO allow citing of images in Projects. Since attached to the last user message, it has no text associated with it.
        # One future workaround is to include the images as separate user messages with citation information and process those.
        always_cite_documents: bool = bool(
            context_files.use_as_search_filter or context_files.file_texts
        )
        should_cite_documents: bool = False
        ran_image_gen: bool = False
        just_ran_web_search: bool = False
        has_open_url_tool: bool = any(isinstance(tool, OpenURLTool) for tool in tools)
        has_called_search_tool: bool = False
        code_interpreter_file_generated: bool = False
        fallback_extraction_attempted: bool = False
        citation_mapping: dict[int, str] = {}  # Maps citation_num -> document_id/URL

        # Fetch this in a short-lived session so the long-running stream loop does
        # not pin a connection just to keep read state alive.
        with get_session_with_current_tenant() as prompt_db_session:
            default_base_system_prompt: str = get_default_base_system_prompt(
                prompt_db_session
            )
        system_prompt = None
        custom_agent_prompt_msg = None

        # Resolve author-controlled `{{user.<key>}}` placeholders in the
        # agent's prompts against the current user's directory profile (+
        # basic identity) once, before the cycle loop — so every branch below
        # and every token count sees the final text. Never mutate the shared
        # `persona`.
        placeholder_values = (
            user_memory_context.user_info.placeholder_values
            if user_memory_context
            else {}
        )
        custom_agent_prompt = (
            substitute_user_placeholders(custom_agent_prompt, placeholder_values)
            if custom_agent_prompt
            else custom_agent_prompt
        )
        persona_system_prompt = (
            substitute_user_placeholders(persona.system_prompt, placeholder_values)
            if persona and persona.system_prompt
            else None
        )
        persona_task_prompt = (
            substitute_user_placeholders(persona.task_prompt, placeholder_values)
            if persona and persona.task_prompt
            else None
        )

        reasoning_cycles = 0
        for llm_cycle_count in range(MAX_LLM_CYCLES):
            # Handling tool calls based on cycle count and past cycle conditions
            out_of_cycles = llm_cycle_count == MAX_LLM_CYCLES - 1
            if forced_tool_id:
                # Needs to be just the single one because the "required" currently doesn't have a specified tool, just a binary
                final_tools = [tool for tool in tools if tool.id == forced_tool_id]
                if not final_tools:
                    raise ValueError(f"Tool {forced_tool_id} not found in tools")
                tool_choice = ToolChoiceOptions.REQUIRED
                forced_tool_id = None
            elif out_of_cycles or ran_image_gen:
                # Last cycle, no tools allowed, just answer!
                tool_choice = ToolChoiceOptions.NONE
                final_tools = []
            else:
                tool_choice = ToolChoiceOptions.AUTO
                final_tools = tools

            # Handling the system prompt and custom agent prompt
            # The section below calculates the available tokens for history a bit more accurately
            # now that project files are loaded in.
            persona_datetime_aware = persona.datetime_aware if persona else True
            cite_documents = should_cite_documents or always_cite_documents
            if persona and persona.replace_base_system_prompt:
                # Handles the case where user has checked off the "Replace base system prompt" checkbox
                processed_system_prompt = (
                    process_prompt_template(
                        persona_system_prompt,
                        datetime_aware=persona_datetime_aware,
                        append_datetime_if_aware=True,
                        should_cite_documents=cite_documents,
                    )
                    if persona_system_prompt
                    else None
                )
                system_prompt = (
                    ChatMessageSimple(
                        message=processed_system_prompt,
                        token_count=token_counter(processed_system_prompt),
                        message_type=MessageType.SYSTEM,
                    )
                    if processed_system_prompt
                    else None
                )
                custom_agent_prompt_msg = None
            else:
                # If it's an empty string, we assume the user does not want to include it as an empty System message
                if default_base_system_prompt:
                    prompt_memory_context = (
                        user_memory_context
                        if inject_memories_in_prompt
                        else (
                            user_memory_context.without_memories()
                            if user_memory_context
                            else None
                        )
                    )
                    system_prompt_str = build_system_prompt(
                        base_system_prompt=default_base_system_prompt,
                        datetime_aware=persona_datetime_aware,
                        user_memory_context=prompt_memory_context,
                        tools=tools,
                        should_cite_documents=cite_documents,
                    )
                    system_prompt = ChatMessageSimple(
                        message=system_prompt_str,
                        token_count=token_counter(system_prompt_str),
                        message_type=MessageType.SYSTEM,
                    )
                    processed_custom_agent_prompt = (
                        process_prompt_template(
                            custom_agent_prompt,
                            datetime_aware=persona_datetime_aware,
                            append_datetime_if_aware=False,
                            should_cite_documents=cite_documents,
                        )
                        if custom_agent_prompt
                        else None
                    )
                    custom_agent_prompt_msg = (
                        ChatMessageSimple(
                            message=processed_custom_agent_prompt,
                            token_count=token_counter(processed_custom_agent_prompt),
                            message_type=MessageType.USER,
                        )
                        if processed_custom_agent_prompt
                        else None
                    )
                else:
                    # If there is a custom agent prompt, it replaces the system prompt when the default system prompt is empty
                    processed_custom_agent_prompt = (
                        process_prompt_template(
                            custom_agent_prompt,
                            datetime_aware=persona_datetime_aware,
                            append_datetime_if_aware=True,
                            should_cite_documents=cite_documents,
                        )
                        if custom_agent_prompt
                        else None
                    )
                    system_prompt = (
                        ChatMessageSimple(
                            message=processed_custom_agent_prompt,
                            token_count=token_counter(processed_custom_agent_prompt),
                            message_type=MessageType.SYSTEM,
                        )
                        if processed_custom_agent_prompt
                        else None
                    )
                    custom_agent_prompt_msg = None

            processed_task_prompt = (
                process_prompt_template(
                    persona_task_prompt,
                    datetime_aware=persona_datetime_aware,
                    append_datetime_if_aware=False,
                    should_cite_documents=cite_documents,
                )
                if persona_task_prompt
                else None
            )
            reminder_message_text = select_reminder_text(
                ran_image_gen=ran_image_gen,
                just_ran_web_search=just_ran_web_search,
                has_open_url_tool=has_open_url_tool,
                out_of_cycles=out_of_cycles,
                persona_task_prompt=processed_task_prompt,
                include_citation_reminder=should_cite_documents
                or always_cite_documents,
                include_file_reminder=code_interpreter_file_generated,
            )

            reminder_msg = (
                ChatMessageSimple(
                    message=reminder_message_text,
                    token_count=token_counter(reminder_message_text),
                    message_type=MessageType.USER_REMINDER,
                )
                if reminder_message_text
                else None
            )

            tool_token_budget = compute_all_tool_tokens(final_tools, token_counter)
            truncated_message_history = construct_message_history(
                system_prompt=system_prompt,
                custom_agent_prompt=custom_agent_prompt_msg,
                simple_chat_history=simple_chat_history,
                reminder_message=reminder_msg,
                context_files=context_files,
                available_tokens=max(0, available_tokens - tool_token_budget),
                token_counter=token_counter,
                all_injected_file_metadata=all_injected_file_metadata,
                image_files_replayed_as_markers=image_files_replayed_as_markers,
            )

            # This calls the LLM, yields packets (reasoning, answers, etc.) and returns the result
            # It also pre-processes the tool calls in preparation for running them
            tool_defs = [tool.tool_definition() for tool in final_tools]

            # Calculate total processing time from loop start until now
            # This measures how long the user waits before the answer starts streaming
            pre_answer_processing_time = time.monotonic() - loop_start_time

            llm_step_result, has_reasoned = run_llm_step(
                emitter=emitter,
                history=truncated_message_history,
                tool_definitions=tool_defs,
                tool_choice=tool_choice,
                llm=llm,
                placement=Placement(turn_index=llm_cycle_count + reasoning_cycles),
                citation_processor=citation_processor,
                state_container=state_container,
                # The rich docs representation is passed in so that when yielding the answer, it can also
                # immediately yield the full set of found documents. This gives us the option to show the
                # final set of documents immediately if desired.
                final_documents=gathered_documents,
                user_identity=user_identity,
                pre_answer_processing_time=pre_answer_processing_time,
                reasoning_effort=reasoning_effort,
            )
            if has_reasoned:
                reasoning_cycles += 1

            # Fallback extraction for LLMs that don't support tool calling natively or are lower quality
            # and might incorrectly output tool calls in other channels
            llm_step_result, attempted = _try_fallback_tool_extraction(
                llm_step_result=llm_step_result,
                tool_choice=tool_choice,
                fallback_extraction_attempted=fallback_extraction_attempted,
                tool_defs=tool_defs,
                turn_index=llm_cycle_count + reasoning_cycles,
            )
            if attempted:
                # To prevent the case of excessive looping with bad models, we only allow one fallback attempt
                fallback_extraction_attempted = True

            # Save citation mapping after each LLM step for incremental state updates
            state_container.set_citation_mapping(citation_processor.citation_to_doc)

            # Run the LLM selected tools, there is some more logic here than a simple execution
            # each tool might have custom logic here
            tool_responses: list[ToolResponse] = []
            tool_calls = llm_step_result.tool_calls or []

            if INTEGRATION_TESTS_MODE and tool_calls:
                for tool_call in tool_calls:
                    emitter.emit(
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
                emitter.emit(
                    Packet(
                        placement=Placement(
                            turn_index=tool_calls[0].placement.turn_index
                        ),
                        obj=TopLevelBranching(num_parallel_branches=len(tool_calls)),
                    )
                )

            # Quick note for why citation_mapping and citation_processors are both needed:
            # 1. Tools return lightweight string mappings, not SearchDoc objects
            # 2. The SearchDoc resolution is deliberately deferred to llm_loop.py
            # 3. The citation_processor operates on SearchDoc objects and can't provide a complete reverse URL lookup for
            # in-flight citations
            # It can be cleaned up but not super trivial or worthwhile right now
            just_ran_web_search = False
            parallel_tool_call_results = run_tool_calls(
                tool_calls=tool_calls,
                tools=final_tools,
                message_history=truncated_message_history,
                user_memory_context=user_memory_context,
                user_info=None,  # TODO, this is part of memories right now, might want to separate it out
                citation_mapping=citation_mapping,
                next_citation_num=citation_processor.get_next_citation_number(),
                max_concurrent_tools=None,
                skip_search_query_expansion=has_called_search_tool,
                chat_files=chat_files,
                url_snippet_map=extract_url_snippet_map(gathered_documents or []),
                inject_memories_in_prompt=inject_memories_in_prompt,
            )
            tool_responses = parallel_tool_call_results.tool_responses
            citation_mapping = parallel_tool_call_results.updated_citation_mapping

            # Failure case, give something reasonable to the LLM to try again
            if tool_calls and not tool_responses:
                failure_messages = create_tool_call_failure_messages(
                    tool_calls, token_counter
                )
                simple_chat_history.extend(failure_messages)
                continue

            for tool_response in tool_responses:
                # Extract tool_call from the response (set by run_tool_calls)
                if tool_response.tool_call is None:
                    raise ValueError("Tool response missing tool_call reference")

                tool_call = tool_response.tool_call
                tab_index = tool_call.placement.tab_index

                # Track if search tool was called (for skipping query expansion on subsequent calls)
                if tool_call.tool_name == SearchTool.NAME:
                    has_called_search_tool = True

                # Track if code interpreter generated files with download links
                if (
                    tool_call.tool_name == PythonTool.NAME
                    and not code_interpreter_file_generated
                ):
                    try:
                        parsed = json.loads(tool_response.llm_facing_response)
                        if parsed.get("generated_files"):
                            code_interpreter_file_generated = True
                    except (json.JSONDecodeError, AttributeError):
                        pass

                tools_by_name = {tool.name: tool for tool in final_tools}

                # Add the results to the chat history. Even though tools may run in parallel,
                # LLM APIs require linear history, so results are added sequentially.
                # Get the tool object to retrieve tool_id
                tool = tools_by_name.get(tool_call.tool_name)
                if not tool:
                    raise ValueError(
                        f"Tool '{tool_call.tool_name}' not found in tools list"
                    )

                # Extract search_docs if this is a search tool response
                search_docs = None
                displayed_docs = None
                if isinstance(tool_response.rich_response, SearchDocsResponse):
                    search_docs = tool_response.rich_response.search_docs
                    displayed_docs = tool_response.rich_response.displayed_docs

                    # Add ALL search docs to state container for DB persistence
                    if search_docs:
                        state_container.add_search_docs(search_docs)

                    if gathered_documents:
                        gathered_documents.extend(search_docs)
                    else:
                        gathered_documents = search_docs

                    # This is used for the Open URL reminder in the next cycle
                    # only do this if the web search tool yielded results
                    if search_docs and tool_call.tool_name == WebSearchTool.NAME:
                        just_ran_web_search = True

                    # Stage any raw source files attached to these hits into
                    # the session's chat_files so the next Python tool call
                    # sees them already uploaded under their display names.
                    if search_docs:
                        staged = build_python_chat_files_from_search_docs(
                            search_docs=search_docs,
                        )
                        if staged:
                            existing_filenames = {cf.filename for cf in chat_files}
                            chat_files.extend(
                                cf
                                for cf in staged
                                if cf.filename not in existing_filenames
                            )

                # Extract generated_images if this is an image generation tool response
                generated_images = None
                if isinstance(
                    tool_response.rich_response, FinalImageGenerationResponse
                ):
                    generated_images = tool_response.rich_response.generated_images

                # Extract generated_files if this is a code interpreter response
                generated_files = None
                if isinstance(tool_response.rich_response, PythonToolRichResponse):
                    generated_files = (
                        tool_response.rich_response.generated_files or None
                    )

                # Custom tools save image/CSV blobs and return their ids.
                generated_file_ids = None
                if isinstance(
                    tool_response.rich_response, CustomToolCallSummary
                ) and isinstance(
                    tool_response.rich_response.tool_result, CustomToolUserFileSnapshot
                ):
                    generated_file_ids = (
                        tool_response.rich_response.tool_result.file_ids or None
                    )

                # Persist memory if this is a memory tool response
                memory_snapshot: MemoryToolResponseSnapshot | None = None
                incognito_memory_refusal: str | None = None
                if isinstance(tool_response.rich_response, MemoryToolResponse):
                    # Any incognito mode refuses memory writes with an explicit
                    # error, so neither the model nor the user sees a saved
                    # memory that does not exist.
                    if get_current_incognito_record_mode() is not None:
                        incognito_memory_refusal = (
                            "Error: memories cannot be saved from an incognito "
                            "chat. Tell the user their request was not saved."
                        )
                    else:
                        persisted_memory_id: int | None = None
                        if user_memory_context and user_memory_context.user_id:
                            if tool_response.rich_response.index_to_replace is not None:
                                persisted_memory_id = update_memory_at_index(
                                    user_id=user_memory_context.user_id,
                                    index=tool_response.rich_response.index_to_replace,
                                    new_text=tool_response.rich_response.memory_text,
                                )
                            else:
                                persisted_memory_id = add_memory(
                                    user_id=user_memory_context.user_id,
                                    memory_text=tool_response.rich_response.memory_text,
                                )
                        operation: Literal["add", "update"] = (
                            "update"
                            if tool_response.rich_response.index_to_replace is not None
                            else "add"
                        )
                        memory_snapshot = MemoryToolResponseSnapshot(
                            memory_text=tool_response.rich_response.memory_text,
                            operation=operation,
                            memory_id=persisted_memory_id,
                            index=tool_response.rich_response.index_to_replace,
                        )

                if incognito_memory_refusal:
                    saved_response = incognito_memory_refusal
                    # The next LLM cycle must see the refusal too.
                    tool_response.llm_facing_response = incognito_memory_refusal
                elif memory_snapshot:
                    saved_response = json.dumps(memory_snapshot.model_dump())
                elif isinstance(tool_response.rich_response, CustomToolCallSummary):
                    saved_response = json.dumps(
                        tool_response.rich_response.model_dump()
                    )
                elif isinstance(tool_response.rich_response, str):
                    saved_response = tool_response.rich_response
                else:
                    saved_response = tool_response.llm_facing_response

                tool_call_info = ToolCallInfo(
                    parent_tool_call_id=None,  # Top-level tool calls are attached to the chat message
                    turn_index=llm_cycle_count + reasoning_cycles,
                    tab_index=tab_index,
                    tool_name=tool_call.tool_name,
                    tool_call_id=tool_call.tool_call_id,
                    tool_id=tool.id,
                    reasoning_tokens=llm_step_result.reasoning,  # All tool calls from this loop share the same reasoning
                    tool_call_arguments=tool_call.tool_args,
                    tool_call_response=saved_response,
                    search_docs=displayed_docs or search_docs,
                    generated_images=generated_images,
                    generated_files=generated_files,
                    generated_file_ids=generated_file_ids,
                )
                # Add to state container for partial save support
                state_container.add_tool_call(tool_call_info)

                # Update citation processor if this was a search tool
                update_citation_processor_from_tool_response(
                    tool_response, citation_processor
                )

            # After processing all tool responses for this turn, add messages to history
            # using OpenAI parallel tool calling format:
            # 1. ONE ASSISTANT message with tool_calls array
            # 2. N TOOL_CALL_RESPONSE messages (one per tool call)
            if tool_responses:
                # Filter to only responses with valid tool_call references
                valid_tool_responses = [
                    tr for tr in tool_responses if tr.tool_call is not None
                ]

                # Build ToolCallSimple list for all tool calls in this turn
                tool_calls_simple: list[ToolCallSimple] = []
                for tool_response in valid_tool_responses:
                    tc = tool_response.tool_call
                    assert (
                        tc is not None
                    )  # Already filtered above, this is just for typing purposes

                    tool_call_message = tc.to_msg_str()
                    tool_call_token_count = token_counter(tool_call_message)

                    tool_calls_simple.append(
                        ToolCallSimple(
                            tool_call_id=tc.tool_call_id,
                            tool_name=tc.tool_name,
                            tool_arguments=tc.tool_args,
                            token_count=tool_call_token_count,
                        )
                    )

                # Create ONE ASSISTANT message with all tool calls for this turn
                total_tool_call_tokens = sum(tc.token_count for tc in tool_calls_simple)
                assistant_with_tools = ChatMessageSimple(
                    message="",  # No text content when making tool calls
                    token_count=total_tool_call_tokens,
                    message_type=MessageType.ASSISTANT,
                    tool_calls=tool_calls_simple,
                    image_files=None,
                )
                simple_chat_history.append(assistant_with_tools)

                # Add TOOL_CALL_RESPONSE messages for each tool call
                for tool_response in valid_tool_responses:
                    tc = tool_response.tool_call
                    assert tc is not None  # Already filtered above

                    tool_response_message = tool_response.llm_facing_response
                    tool_response_token_count = token_counter(tool_response_message)

                    tool_response_msg = ChatMessageSimple(
                        message=tool_response_message,
                        token_count=tool_response_token_count,
                        message_type=MessageType.TOOL_CALL_RESPONSE,
                        tool_call_id=tc.tool_call_id,
                        image_files=None,
                    )
                    simple_chat_history.append(tool_response_msg)

            # If no tool calls, then it must have answered, wrap up
            if not llm_step_result.tool_calls or len(llm_step_result.tool_calls) == 0:
                break

            # Certain tools do not allow further actions, force the LLM wrap up on the next cycle
            if any(
                tool.tool_name in STOPPING_TOOLS_NAMES
                for tool in llm_step_result.tool_calls
            ):
                ran_image_gen = True

            if llm_step_result.tool_calls and any(
                tool.tool_name in CITEABLE_TOOLS_NAMES
                for tool in llm_step_result.tool_calls
            ):
                # As long as 1 tool with citeable documents is called at any point, we ask the LLM to try to cite
                should_cite_documents = True

        if not llm_step_result.answer and not llm_step_result.tool_calls:
            raise _build_empty_llm_response_error(
                llm=llm,
                llm_step_result=llm_step_result,
                tool_choice=tool_choice,
            )

        if not llm_step_result.answer:
            raise RuntimeError(
                "The LLM did not return a final answer after tool execution. "
                "Typically this indicates invalid tool-call output, a model/provider mismatch, "
                "or serving API misconfiguration."
            )

        emitter.emit(
            Packet(
                placement=Placement(
                    turn_index=llm_cycle_count  # ty: ignore[possibly-unresolved-reference]
                    + reasoning_cycles
                ),
                obj=OverallStop(type="stop"),
            )
        )
