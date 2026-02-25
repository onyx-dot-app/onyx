import json
import time
from collections.abc import Callable
from typing import Literal

from sqlalchemy.orm import Session

from onyx.chat.chat_state import ChatStateContainer
from onyx.chat.chat_utils import create_tool_call_failure_messages
from onyx.chat.citation_processor import CitationMapping
from onyx.chat.citation_processor import CitationMode
from onyx.chat.citation_processor import DynamicCitationProcessor
from onyx.chat.citation_utils import update_citation_processor_from_tool_response
from onyx.chat.emitter import Emitter
from onyx.chat.llm_step import extract_tool_calls_from_response_text
from onyx.chat.llm_step import run_llm_step
from onyx.chat.models import ChatMessageSimple
from onyx.chat.models import ExtractedProjectFiles
from onyx.chat.models import FileToolMetadata
from onyx.chat.models import LlmStepResult
from onyx.chat.models import ProjectFileMetadata
from onyx.chat.models import ToolCallSimple
from onyx.chat.prompt_utils import build_reminder_message
from onyx.chat.prompt_utils import build_system_prompt
from onyx.chat.prompt_utils import (
    get_default_base_system_prompt,
)
from onyx.configs.app_configs import INTEGRATION_TESTS_MODE
from onyx.configs.constants import DocumentSource
from onyx.configs.constants import MessageType
from onyx.context.search.models import SearchDoc
from onyx.context.search.models import SearchDocsResponse
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.memory import add_memory
from onyx.db.memory import update_memory_at_index
from onyx.db.memory import UserMemoryContext
from onyx.db.models import Persona
from onyx.llm.constants import LlmProviderNames
from onyx.llm.interfaces import LLM
from onyx.llm.interfaces import LLMUserIdentity
from onyx.llm.interfaces import ToolChoiceOptions
from onyx.prompts.chat_prompts import IMAGE_GEN_REMINDER
from onyx.prompts.chat_prompts import OPEN_URL_REMINDER
from onyx.server.query_and_chat.placement import Placement
from onyx.server.query_and_chat.streaming_models import OverallStop
from onyx.server.query_and_chat.streaming_models import Packet
from onyx.server.query_and_chat.streaming_models import ToolCallDebug
from onyx.server.query_and_chat.streaming_models import TopLevelBranching
from onyx.tools.built_in_tools import CITEABLE_TOOLS_NAMES
from onyx.tools.built_in_tools import STOPPING_TOOLS_NAMES
from onyx.tools.interface import Tool
from onyx.tools.models import ChatFile
from onyx.tools.models import MemoryToolResponseSnapshot
from onyx.tools.models import ToolCallInfo
from onyx.tools.models import ToolCallKickoff
from onyx.tools.models import ToolResponse
from onyx.tools.tool_implementations.images.models import (
    FinalImageGenerationResponse,
)
from onyx.tools.tool_implementations.memory.models import MemoryToolResponse
from onyx.tools.tool_implementations.python.python_tool import PythonTool
from onyx.tools.tool_implementations.search.search_tool import SearchTool
from onyx.tools.tool_implementations.web_search.utils import extract_url_snippet_map
from onyx.tools.tool_implementations.web_search.web_search_tool import WebSearchTool
from onyx.tools.tool_runner import run_tool_calls
from onyx.tracing.framework.create import trace
from onyx.utils.logger import setup_logger
from shared_configs.contextvars import get_current_tenant_id

logger = setup_logger()


def _looks_like_xml_tool_call_payload(text: str | None) -> bool:
    """Detect XML-style marshaled tool calls emitted as plain text."""
    if not text:
        return False
    lowered = text.lower()
    return (
        "<function_calls" in lowered
        and "<invoke" in lowered
        and "<parameter" in lowered
    )


def _should_keep_bedrock_tool_definitions(
    llm: object, simple_chat_history: list[ChatMessageSimple]
) -> bool:
    """Bedrock requires tool config when history includes toolUse/toolResult blocks."""
    model_provider = getattr(getattr(llm, "config", None), "model_provider", None)
    if model_provider not in {
        LlmProviderNames.BEDROCK,
        LlmProviderNames.BEDROCK_CONVERSE,
    }:
        return False

    return any(
        (
            msg.message_type == MessageType.ASSISTANT
            and msg.tool_calls
            and len(msg.tool_calls) > 0
        )
        or msg.message_type == MessageType.TOOL_CALL_RESPONSE
        for msg in simple_chat_history
    )


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
            f"Extracted {len(extracted_tool_calls)} tool call(s) from response text "
            "as fallback"
        )
        return (
            LlmStepResult(
                reasoning=llm_step_result.reasoning,
                answer=llm_step_result.answer,
                tool_calls=extracted_tool_calls,
                raw_answer=llm_step_result.raw_answer,
            ),
            True,
        )

    return llm_step_result, True


# Hardcoded oppinionated value, might breaks down to something like:
# Cycle 1: Calls web_search for something
# Cycle 2: Calls open_url for some results
# Cycle 3: Calls web_search for some other aspect of the question
# Cycle 4: Calls open_url for some results
# Cycle 5: Maybe call open_url for some additional results or because last set failed
# Cycle 6: No more tools available, forced to answer
MAX_LLM_CYCLES = 6


def _build_project_file_citation_mapping(
    project_file_metadata: list[ProjectFileMetadata],
    starting_citation_num: int = 1,
) -> CitationMapping:
    """Build citation mapping for project files.

    Converts project file metadata into SearchDoc objects that can be cited.
    Citation numbers start from the provided starting number.

    Args:
        project_file_metadata: List of project file metadata
        starting_citation_num: Starting citation number (default: 1)

    Returns:
        Dictionary mapping citation numbers to SearchDoc objects
    """
    citation_mapping: CitationMapping = {}

    for idx, file_meta in enumerate(project_file_metadata, start=starting_citation_num):
        # Create a SearchDoc for each project file
        search_doc = SearchDoc(
            document_id=file_meta.file_id,
            chunk_ind=0,
            semantic_identifier=file_meta.filename,
            link=None,
            blurb=file_meta.file_content,
            source_type=DocumentSource.FILE,
            boost=1,
            hidden=False,
            metadata={},
            score=0.0,
            match_highlights=[file_meta.file_content],
        )
        citation_mapping[idx] = search_doc

    return citation_mapping


def _build_project_message(
    project_files: ExtractedProjectFiles | None,
    token_counter: Callable[[str], int] | None,
) -> list[ChatMessageSimple]:
    """Build messages for project / tool-backed files.

    Returns up to two messages:
    1. The full-text project files message (if project_file_texts is populated).
    2. A lightweight metadata message for files the LLM should access via the
       FileReaderTool (e.g. oversized chat-attached files or project files that
       don't fit in context).
    """
    if not project_files:
        return []

    messages: list[ChatMessageSimple] = []
    if project_files.project_file_texts:
        messages.append(
            _create_project_files_message(project_files, token_counter=None)
        )
    if project_files.file_metadata_for_tool and token_counter:
        messages.append(
            _create_file_tool_metadata_message(
                project_files.file_metadata_for_tool, token_counter
            )
        )
    return messages


def construct_message_history(
    system_prompt: ChatMessageSimple | None,
    custom_agent_prompt: ChatMessageSimple | None,
    simple_chat_history: list[ChatMessageSimple],
    reminder_message: ChatMessageSimple | None,
    project_files: ExtractedProjectFiles | None,
    available_tokens: int,
    last_n_user_messages: int | None = None,
    token_counter: Callable[[str], int] | None = None,
    all_injected_file_metadata: dict[str, FileToolMetadata] | None = None,
) -> list[ChatMessageSimple]:
    if last_n_user_messages is not None:
        if last_n_user_messages <= 0:
            raise ValueError(
                "filtering chat history by last N user messages must be a value greater than 0"
            )

    # Build the project / file-metadata messages up front so we can use their
    # actual token counts for the budget.
    project_messages = _build_project_message(project_files, token_counter)
    project_messages_tokens = sum(m.token_count for m in project_messages)

    history_token_budget = available_tokens
    history_token_budget -= system_prompt.token_count if system_prompt else 0
    history_token_budget -= (
        custom_agent_prompt.token_count if custom_agent_prompt else 0
    )
    history_token_budget -= project_messages_tokens
    history_token_budget -= reminder_message.token_count if reminder_message else 0

    if history_token_budget < 0:
        raise ValueError("Not enough tokens available to construct message history")

    if system_prompt:
        system_prompt.should_cache = True

    # If no history, build minimal context
    if not simple_chat_history:
        result = [system_prompt] if system_prompt else []
        if custom_agent_prompt:
            result.append(custom_agent_prompt)
        result.extend(project_messages)
        if reminder_message:
            result.append(reminder_message)
        return result

    # If last_n_user_messages is set, filter history to only include the last n user messages
    if last_n_user_messages is not None:
        # Find all user message indices
        user_msg_indices = [
            i
            for i, msg in enumerate(simple_chat_history)
            if msg.message_type == MessageType.USER
        ]

        if not user_msg_indices:
            raise ValueError("No user message found in simple_chat_history")

        # If we have more than n user messages, keep only the last n
        if len(user_msg_indices) > last_n_user_messages:
            # Find the index of the n-th user message from the end
            # For example, if last_n_user_messages=2, we want the 2nd-to-last user message
            nth_user_msg_index = user_msg_indices[-(last_n_user_messages)]
            # Keep everything from that user message onwards
            simple_chat_history = simple_chat_history[nth_user_msg_index:]

    # Find the last USER message in the history
    # The history may contain tool calls and responses after the last user message
    last_user_msg_index = None
    for i in range(len(simple_chat_history) - 1, -1, -1):
        if simple_chat_history[i].message_type == MessageType.USER:
            last_user_msg_index = i
            break

    if last_user_msg_index is None:
        raise ValueError("No user message found in simple_chat_history")

    # Split history into three parts:
    # 1. History before the last user message
    # 2. The last user message
    # 3. Messages after the last user message (tool calls, responses, etc.)
    history_before_last_user = simple_chat_history[:last_user_msg_index]
    last_user_message = simple_chat_history[last_user_msg_index]
    messages_after_last_user = simple_chat_history[last_user_msg_index + 1 :]

    # Calculate tokens needed for the last user message and everything after it
    last_user_tokens = last_user_message.token_count
    after_user_tokens = sum(msg.token_count for msg in messages_after_last_user)

    # Check if we can fit at least the last user message and messages after it
    required_tokens = last_user_tokens + after_user_tokens
    if required_tokens > history_token_budget:
        raise ValueError(
            f"Not enough tokens to include the last user message and subsequent messages. "
            f"Required: {required_tokens}, Available: {history_token_budget}"
        )

    # Calculate remaining budget for history before the last user message
    remaining_budget = history_token_budget - required_tokens

    # Truncate history_before_last_user from the top to fit in remaining budget.
    # Track dropped file messages so we can provide their metadata to the
    # FileReaderTool instead.
    truncated_history_before: list[ChatMessageSimple] = []
    dropped_file_ids: list[str] = []
    current_token_count = 0

    for msg in reversed(history_before_last_user):
        if current_token_count + msg.token_count <= remaining_budget:
            msg.should_cache = True
            truncated_history_before.insert(0, msg)
            current_token_count += msg.token_count
        else:
            # Can't fit this message, stop truncating.
            # This message and everything older is dropped.
            break

    # Collect file_ids from ALL dropped messages (those not in
    # truncated_history_before). The truncation loop above keeps the most
    # recent messages, so the dropped ones are at the start of the original
    # list up to (len(history) - len(kept)).
    num_kept = len(truncated_history_before)
    for msg in history_before_last_user[: len(history_before_last_user) - num_kept]:
        if msg.file_id is not None:
            dropped_file_ids.append(msg.file_id)

    # Also treat "orphaned" metadata entries as dropped -- these are files
    # from messages removed by summary truncation (before convert_chat_history
    # ran), so no ChatMessageSimple was ever tagged with their file_id.
    if all_injected_file_metadata:
        surviving_file_ids = {
            msg.file_id for msg in simple_chat_history if msg.file_id is not None
        }
        for fid in all_injected_file_metadata:
            if fid not in surviving_file_ids and fid not in dropped_file_ids:
                dropped_file_ids.append(fid)

    # Build a forgotten-files metadata message if any file messages were
    # dropped AND we have metadata for them (meaning the FileReaderTool is
    # available). Reserve tokens for this message in the budget.
    forgotten_files_message: ChatMessageSimple | None = None
    if dropped_file_ids and all_injected_file_metadata and token_counter:
        forgotten_meta = [
            all_injected_file_metadata[fid]
            for fid in dropped_file_ids
            if fid in all_injected_file_metadata
        ]
        if forgotten_meta:
            logger.debug(
                f"FileReader: building forgotten-files message for "
                f"{[(m.file_id, m.filename) for m in forgotten_meta]}"
            )
            forgotten_files_message = _create_file_tool_metadata_message(
                forgotten_meta, token_counter
            )
            # Shrink the remaining budget. If the metadata message doesn't
            # fit we may need to drop more history messages.
            remaining_budget -= forgotten_files_message.token_count
            while truncated_history_before and current_token_count > remaining_budget:
                evicted = truncated_history_before.pop(0)
                current_token_count -= evicted.token_count
                # If the evicted message is itself a file, add it to the
                # forgotten metadata (it's now dropped too).
                if (
                    evicted.file_id is not None
                    and evicted.file_id in all_injected_file_metadata
                    and evicted.file_id not in {m.file_id for m in forgotten_meta}
                ):
                    forgotten_meta.append(all_injected_file_metadata[evicted.file_id])
                    # Rebuild the message with the new entry
                    forgotten_files_message = _create_file_tool_metadata_message(
                        forgotten_meta, token_counter
                    )

    # Attach project images to the last user message
    if project_files and project_files.project_image_files:
        existing_images = last_user_message.image_files or []
        last_user_message = ChatMessageSimple(
            message=last_user_message.message,
            token_count=last_user_message.token_count,
            message_type=last_user_message.message_type,
            image_files=existing_images + project_files.project_image_files,
        )

    # Build the final message list according to README ordering:
    # [system], [history_before_last_user], [custom_agent], [project_files],
    # [forgotten_files], [last_user_message], [messages_after_last_user], [reminder]
    result = [system_prompt] if system_prompt else []

    # 1. Add truncated history before last user message
    result.extend(truncated_history_before)

    # 2. Add custom agent prompt (inserted before last user message)
    if custom_agent_prompt:
        result.append(custom_agent_prompt)

    # 3. Add project files / file-metadata messages (inserted before last user message)
    result.extend(project_messages)

    # 4. Add forgotten-files metadata (right before the user's question)
    if forgotten_files_message:
        result.append(forgotten_files_message)

    # 5. Add last user message (with project images attached)
    result.append(last_user_message)

    # 6. Add messages after last user message (tool calls, responses, etc.)
    result.extend(messages_after_last_user)

    # 7. Add reminder message at the very end
    if reminder_message:
        result.append(reminder_message)

    return _drop_orphaned_tool_call_responses(result)


def _drop_orphaned_tool_call_responses(
    messages: list[ChatMessageSimple],
) -> list[ChatMessageSimple]:
    """Drop tool response messages whose tool_call_id is not in prior assistant tool calls.

    This can happen when history truncation drops an ASSISTANT tool-call message but
    leaves a later TOOL_CALL_RESPONSE message in context. Some providers (e.g. Ollama)
    reject such history with an "unexpected tool call id" error.
    """
    known_tool_call_ids: set[str] = set()
    sanitized: list[ChatMessageSimple] = []

    for msg in messages:
        if msg.message_type == MessageType.ASSISTANT and msg.tool_calls:
            for tool_call in msg.tool_calls:
                known_tool_call_ids.add(tool_call.tool_call_id)
            sanitized.append(msg)
            continue

        if msg.message_type == MessageType.TOOL_CALL_RESPONSE:
            if msg.tool_call_id and msg.tool_call_id in known_tool_call_ids:
                sanitized.append(msg)
            else:
                logger.debug(
                    "Dropping orphaned tool response with tool_call_id=%s while "
                    "constructing message history",
                    msg.tool_call_id,
                )
            continue

        sanitized.append(msg)

    return sanitized


def _create_file_tool_metadata_message(
    file_metadata: list[FileToolMetadata],
    token_counter: Callable[[str], int],
) -> ChatMessageSimple:
    """Build a lightweight metadata-only message listing files available via FileReaderTool.

    Used when files are too large to fit in context and the vector DB is
    disabled, so the LLM must use ``read_file`` to inspect them.
    """
    lines = [
        "You have access to the following files. Use the read_file tool to "
        "read sections of any file:"
    ]
    for meta in file_metadata:
        lines.append(
            f'- {meta.file_id}: "{meta.filename}" (~{meta.approx_char_count:,} chars)'
        )

    message_content = "\n".join(lines)
    return ChatMessageSimple(
        message=message_content,
        token_count=token_counter(message_content),
        message_type=MessageType.USER,
    )


def _create_project_files_message(
    project_files: ExtractedProjectFiles,
    token_counter: Callable[[str], int] | None,  # noqa: ARG001
) -> ChatMessageSimple:
    """Convert project files to a ChatMessageSimple message.

    Format follows the README specification for document representation.
    """
    import json

    # Format as documents JSON as described in README
    documents_list = []
    for idx, file_text in enumerate(project_files.project_file_texts, start=1):
        documents_list.append(
            {
                "document": idx,
                "contents": file_text,
            }
        )

    documents_json = json.dumps({"documents": documents_list}, indent=2)
    message_content = f"Here are some documents provided for context, they may not all be relevant:\n{documents_json}"

    # Use pre-calculated token count from project_files
    return ChatMessageSimple(
        message=message_content,
        token_count=project_files.total_token_count,
        message_type=MessageType.USER,
    )


def run_llm_loop(
    emitter: Emitter,
    state_container: ChatStateContainer,
    simple_chat_history: list[ChatMessageSimple],
    tools: list[Tool],
    custom_agent_prompt: str | None,
    project_files: ExtractedProjectFiles,
    persona: Persona | None,
    user_memory_context: UserMemoryContext | None,
    llm: LLM,
    token_counter: Callable[[str], int],
    db_session: Session,
    forced_tool_id: int | None = None,
    user_identity: LLMUserIdentity | None = None,
    chat_session_id: str | None = None,
    chat_files: list[ChatFile] | None = None,
    include_citations: bool = True,
    all_injected_file_metadata: dict[str, FileToolMetadata] | None = None,
    inject_memories_in_prompt: bool = True,
) -> None:
    with trace(
        "run_llm_loop",
        group_id=chat_session_id,
        metadata={
            "tenant_id": get_current_tenant_id(),
            "chat_session_id": chat_session_id,
        },
    ):
        # Fix some LiteLLM issues,
        from onyx.llm.litellm_singleton.config import (
            initialize_litellm,
        )  # Here for lazy load LiteLLM

        initialize_litellm()

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
        if project_files.project_file_metadata:
            project_citation_mapping = _build_project_file_citation_mapping(
                project_files.project_file_metadata
            )
            citation_processor.update_citation_mapping(project_citation_mapping)

        llm_step_result: LlmStepResult | None = None

        # Pass the total budget to construct_message_history, which will handle token allocation
        available_tokens = llm.config.max_input_tokens
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
            project_files.project_as_filter or project_files.project_file_texts
        )
        should_cite_documents: bool = False
        ran_image_gen: bool = False
        just_ran_web_search: bool = False
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
                # Bedrock requires tool config in requests that include toolUse/toolResult history.
                final_tools = (
                    tools
                    if _should_keep_bedrock_tool_definitions(llm, simple_chat_history)
                    else []
                )
            else:
                tool_choice = ToolChoiceOptions.AUTO
                final_tools = tools

            # Handling the system prompt and custom agent prompt
            # The section below calculates the available tokens for history a bit more accurately
            # now that project files are loaded in.
            if persona and persona.replace_base_system_prompt:
                # Handles the case where user has checked off the "Replace base system prompt" checkbox
                system_prompt = (
                    ChatMessageSimple(
                        message=persona.system_prompt,
                        token_count=token_counter(persona.system_prompt),
                        message_type=MessageType.SYSTEM,
                    )
                    if persona.system_prompt
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
                        datetime_aware=persona.datetime_aware if persona else True,
                        user_memory_context=prompt_memory_context,
                        tools=tools,
                        should_cite_documents=should_cite_documents
                        or always_cite_documents,
                    )
                    system_prompt = ChatMessageSimple(
                        message=system_prompt_str,
                        token_count=token_counter(system_prompt_str),
                        message_type=MessageType.SYSTEM,
                    )
                    custom_agent_prompt_msg = (
                        ChatMessageSimple(
                            message=custom_agent_prompt,
                            token_count=token_counter(custom_agent_prompt),
                            message_type=MessageType.USER,
                        )
                        if custom_agent_prompt
                        else None
                    )
                else:
                    # If there is a custom agent prompt, it replaces the system prompt when the default system prompt is empty
                    system_prompt = (
                        ChatMessageSimple(
                            message=custom_agent_prompt,
                            token_count=token_counter(custom_agent_prompt),
                            message_type=MessageType.SYSTEM,
                        )
                        if custom_agent_prompt
                        else None
                    )
                    custom_agent_prompt_msg = None

            reminder_message_text: str | None
            if ran_image_gen:
                # Some models are trained to give back images to the user for some similar tool
                # This is to prevent it generating things like:
                # [Cute Cat](attachment://a_cute_cat_sitting_playfully.png)
                reminder_message_text = IMAGE_GEN_REMINDER
            elif just_ran_web_search and not out_of_cycles:
                reminder_message_text = OPEN_URL_REMINDER
            else:
                # This is the default case, the LLM at this point may answer so it is important
                # to include the reminder. Potentially this should also mention citation
                reminder_message_text = build_reminder_message(
                    reminder_text=(
                        persona.task_prompt if persona and persona.task_prompt else None
                    ),
                    include_citation_reminder=should_cite_documents
                    or always_cite_documents,
                    include_file_reminder=code_interpreter_file_generated,
                    is_last_cycle=out_of_cycles,
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

            truncated_message_history = construct_message_history(
                system_prompt=system_prompt,
                custom_agent_prompt=custom_agent_prompt_msg,
                simple_chat_history=simple_chat_history,
                reminder_message=reminder_msg,
                project_files=project_files,
                available_tokens=available_tokens,
                token_counter=token_counter,
                all_injected_file_metadata=all_injected_file_metadata,
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

                # Build a mapping of tool names to tool objects for getting tool_id
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

                # Extract generated_images if this is an image generation tool response
                generated_images = None
                if isinstance(
                    tool_response.rich_response, FinalImageGenerationResponse
                ):
                    generated_images = tool_response.rich_response.generated_images

                # Persist memory if this is a memory tool response
                memory_snapshot: MemoryToolResponseSnapshot | None = None
                if isinstance(tool_response.rich_response, MemoryToolResponse):
                    persisted_memory_id: int | None = None
                    if user_memory_context and user_memory_context.user_id:
                        if tool_response.rich_response.index_to_replace is not None:
                            memory = update_memory_at_index(
                                user_id=user_memory_context.user_id,
                                index=tool_response.rich_response.index_to_replace,
                                new_text=tool_response.rich_response.memory_text,
                                db_session=db_session,
                            )
                            persisted_memory_id = memory.id if memory else None
                        else:
                            memory = add_memory(
                                user_id=user_memory_context.user_id,
                                memory_text=tool_response.rich_response.memory_text,
                                db_session=db_session,
                            )
                            persisted_memory_id = memory.id
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

                if memory_snapshot:
                    saved_response = json.dumps(memory_snapshot.model_dump())
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

        if not llm_step_result or not llm_step_result.answer:
            raise RuntimeError(
                "The LLM did not return an answer. "
                "Typically this is an issue with LLMs that do not support tool calling natively, "
                "or the model serving API is not configured correctly. "
                "This may also happen with models that are lower quality outputting invalid tool calls."
            )

        emitter.emit(
            Packet(
                placement=Placement(turn_index=llm_cycle_count + reasoning_cycles),
                obj=OverallStop(type="stop"),
            )
        )
