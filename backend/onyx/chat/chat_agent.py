import json
import threading
import time
from collections.abc import Callable
from typing import Any

from pydantic_ai import RunContext
from pydantic_ai import messages as pm
from pydantic_ai.tools import ToolDefinition
from pydantic_ai_harness.compaction import estimate_token_count

from onyx.chat.agent_memory import create_memory_capability
from onyx.chat.agent_runtime import NativeAgentRequest, run_native_agent
from onyx.chat.chat_state import ChatStateContainer
from onyx.chat.chat_utils import (
    build_python_chat_files_from_search_docs,
)
from onyx.chat.citation_processor import (
    CitationMapping,
    CitationMode,
    DynamicCitationProcessor,
)
from onyx.chat.citation_utils import update_citation_processor_from_tool_response
from onyx.chat.emitter import Emitter
from onyx.chat.history_translation import translate_history_to_native_messages
from onyx.chat.models import (
    ChatMessageSimple,
    ContextFileMetadata,
    ExtractedContextFiles,
    FileToolMetadata,
)
from onyx.chat.prompt_utils import (
    build_reminder_message,
    build_system_prompt,
    get_default_base_system_prompt,
    process_prompt_template,
)
from onyx.chat.token_budget import resolve_chat_token_budget
from onyx.configs.app_configs import INTEGRATION_TESTS_MODE
from onyx.configs.chat_configs import MAX_LLM_CYCLES
from onyx.configs.constants import DocumentSource, MessageType
from onyx.context.search.models import SearchDoc, SearchDocsResponse
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.memory import UserMemoryContext
from onyx.db.models import Persona
from onyx.file_store.models import ChatFileType
from onyx.llm.constants import LlmProviderNames
from onyx.llm.exceptions import ClassifiedLLMError
from onyx.llm.interfaces import LLM, LLMUserIdentity, ToolChoiceOptions
from onyx.llm.model_capabilities import is_true_openai_model
from onyx.llm.models import ReasoningEffort
from onyx.prompts.chat_prompts import (
    IMAGE_GEN_REMINDER,
    NON_VISION_IMAGE_MARKER,
    OPEN_URL_REMINDER,
)
from onyx.prompts.prompt_utils import substitute_user_placeholders
from onyx.server.query_and_chat.placement import Placement
from onyx.server.query_and_chat.streaming_models import (
    OverallStop,
    Packet,
    ToolCallDebug,
    TopLevelBranching,
)
from onyx.tools.built_in_tools import CITEABLE_TOOLS_NAMES, STOPPING_TOOLS_NAMES
from onyx.tools.constants import FILE_READER_TOOL_NAME
from onyx.tools.interface import Tool
from onyx.tools.models import (
    ChatFile,
    CustomToolCallSummary,
    CustomToolUserFileSnapshot,
    PythonToolRichResponse,
    ToolCallInfo,
    ToolCallKickoff,
    ToolResponse,
)
from onyx.tools.progress import check_tool_run_active
from onyx.tools.tool_implementations.images.models import FinalImageGenerationResponse
from onyx.tools.tool_implementations.memory.memory_tool import MemoryTool
from onyx.tools.tool_implementations.open_url.open_url_tool import OpenURLTool
from onyx.tools.tool_implementations.python.python_tool import PythonTool
from onyx.tools.tool_implementations.search.search_tool import SearchTool
from onyx.tools.tool_implementations.web_search.utils import extract_url_snippet_map
from onyx.tools.tool_implementations.web_search.web_search_tool import WebSearchTool
from onyx.tools.tool_runner import run_tool_call_async
from onyx.tools.utils import compute_all_tool_tokens
from onyx.tracing.framework.create import ChatTraceMetadata, trace
from onyx.utils.logger import setup_logger
from shared_configs.contextvars import (
    get_current_tenant_id,
)

logger = setup_logger()

# Used when no token_counter is available to measure the non-vision image
# marker; intentionally generous so budgeting stays conservative.
_NON_VISION_MARKER_TOKEN_FALLBACK = 40


class EmptyLLMResponseError(ClassifiedLLMError):
    """Raised when the streamed LLM response completes without a usable answer."""

    def __init__(
        self,
        *,
        provider: str,
        model: str,
        tool_choice: ToolChoiceOptions,
        client_error_msg: str,
        error_code: str = "EMPTY_LLM_RESPONSE",
        is_retryable: bool = True,
        finish_reason: str | None = None,
    ) -> None:
        super().__init__(
            client_error_msg=client_error_msg,
            error_code=error_code,
            is_retryable=is_retryable,
        )
        self.provider = provider
        self.model = model
        self.tool_choice = tool_choice
        self.finish_reason = finish_reason


# LiteLLM maps these native policy blocks to content_filter, but gateways may
# forward the provider value unchanged.
_REFUSAL_FINISH_REASONS = {
    "BLOCKLIST",
    "CONTENT_BLOCKED",
    "ERROR_TOXIC",
    "IMAGE_OTHER",
    "IMAGE_PROHIBITED_CONTENT",
    "IMAGE_RECITATION",
    "IMAGE_SAFETY",
    "LANGUAGE",
    "MODEL_ARMOR",
    "OTHER",
    "PROHIBITED_CONTENT",
    "RECITATION",
    "SAFETY",
    "SPII",
    "content_filter",
    "content_filtered",
    "guardrail_intervened",
    "refusal",
    "sensitive",
}


def _build_empty_llm_response_error(
    llm: LLM,
    response: pm.ModelResponse,
    tool_choice: ToolChoiceOptions,
) -> EmptyLLMResponseError:
    provider = llm.config.model_provider
    model = llm.config.model_name
    finish_reason = response.finish_reason

    # A refusal/content-filter stop is a deliberate model decision (HTTP 200
    # with no content), not a transport failure — retrying the same request
    # against the same model will not help.
    if finish_reason in _REFUSAL_FINISH_REASONS:
        model_suggestion = (
            " (e.g. Claude Opus 4.8)" if provider == LlmProviderNames.ANTHROPIC else ""
        )
        return EmptyLLMResponseError(
            provider=provider,
            model=model,
            tool_choice=tool_choice,
            client_error_msg=(
                "The selected model declined to respond to this request and "
                f"returned no content (finish_reason={finish_reason}). Try "
                "rephrasing the request or switching to a different model"
                f"{model_suggestion}."
            ),
            error_code="MODEL_REFUSAL",
            is_retryable=False,
            finish_reason=finish_reason,
        )

    # OpenAI quota exhaustion has reached us as a streamed "stop" with zero content.
    # When the stream is completely empty and there is no reasoning/tool output, surface
    # the likely account-level cause instead of a generic tool-calling error.
    if (
        not response.thinking
        and provider == LlmProviderNames.OPENAI
        and is_true_openai_model(provider, model)
    ):
        return EmptyLLMResponseError(
            provider=provider,
            model=model,
            tool_choice=tool_choice,
            client_error_msg=(
                "The selected OpenAI model returned an empty streamed response "
                "before producing any tokens. This commonly happens when the API "
                "key or project has no remaining quota or billing is not enabled. "
                "Verify quota and billing for this key and try again."
            ),
            error_code="BUDGET_EXCEEDED",
            is_retryable=False,
            finish_reason=finish_reason,
        )

    return EmptyLLMResponseError(
        provider=provider,
        model=model,
        tool_choice=tool_choice,
        client_error_msg=(
            "The selected model returned no final answer before the stream "
            "completed. No text or tool calls were received from the upstream "
            "provider."
        ),
        finish_reason=finish_reason,
    )


def _build_context_file_citation_mapping(
    file_metadata: list[ContextFileMetadata],
    starting_citation_num: int = 1,
) -> CitationMapping:
    """Build citation mapping for context files.

    Converts context file metadata into SearchDoc objects that can be cited.
    Citation numbers start from the provided starting number.

    Args:
        file_metadata: List of context file metadata
        starting_citation_num: Starting citation number (default: 1)

    Returns:
        Dictionary mapping citation numbers to SearchDoc objects
    """
    citation_mapping: CitationMapping = {}

    for idx, file_meta in enumerate(file_metadata, start=starting_citation_num):
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
    context_files: ExtractedContextFiles | None,
    token_counter: Callable[[str], int] | None,
    available_tool_names: set[str] | None = None,
) -> list[ChatMessageSimple]:
    """Build messages for context-injected / tool-backed files.

    Returns up to two messages:
    1. The full-text files message (if file_texts is populated).
    2. A lightweight metadata message for oversized files, naming whichever
       retrieval tool this request actually received.
    """
    if not context_files:
        return []

    messages: list[ChatMessageSimple] = []
    if context_files.file_texts:
        messages.append(
            _create_context_files_message(context_files, token_counter=None)
        )
    if context_files.file_metadata_for_tool and token_counter:
        messages.append(
            _create_file_tool_metadata_message(
                context_files.file_metadata_for_tool,
                token_counter,
                available_tool_names,
            )
        )
    return messages


def count_message_replay_tokens(
    msg: ChatMessageSimple,
    *,
    image_files_replayed_as_markers: bool = False,
    token_counter: Callable[[str], int] | None = None,
) -> int:
    if not image_files_replayed_as_markers:
        return msg.token_count
    # Include images whose stored cost is zero, such as project images.
    num_images = sum(
        1 for f in msg.image_files or [] if f.file_type == ChatFileType.IMAGE
    )
    if not num_images:
        return msg.token_count
    sample_marker = NON_VISION_IMAGE_MARKER.format(file_id="0" * 36)
    marker_tokens = (
        token_counter(sample_marker)
        if token_counter
        else _NON_VISION_MARKER_TOKEN_FALLBACK
    )
    return max(0, msg.token_count - msg.image_token_count) + num_images * marker_tokens


def construct_message_history(
    system_prompt: ChatMessageSimple | None,
    custom_agent_prompt: ChatMessageSimple | None,
    simple_chat_history: list[ChatMessageSimple],
    reminder_message: ChatMessageSimple | None,
    context_files: ExtractedContextFiles | None,
    available_tokens: int,
    last_n_user_messages: int | None = None,
    token_counter: Callable[[str], int] | None = None,
    all_injected_file_metadata: dict[str, FileToolMetadata] | None = None,
    image_files_replayed_as_markers: bool = False,
    available_tool_names: set[str] | None = None,
) -> list[ChatMessageSimple]:
    """Add Onyx context; the agent's compaction capability owns history trimming."""
    history = simple_chat_history
    user_indices = [
        index
        for index, message in enumerate(history)
        if message.message_type == MessageType.USER
    ]
    if last_n_user_messages is not None:
        if last_n_user_messages <= 0:
            raise ValueError("The number of user messages must be positive.")
        if len(user_indices) > last_n_user_messages:
            history = history[user_indices[-last_n_user_messages] :]
            user_indices = [
                index
                for index, message in enumerate(history)
                if message.message_type == MessageType.USER
            ]
    insertion_index = user_indices[-1] if user_indices else len(history)
    context = _build_project_message(context_files, token_counter, available_tool_names)
    if custom_agent_prompt:
        context.insert(0, custom_agent_prompt)
    surviving_file_ids = {message.file_id for message in history if message.file_id}
    forgotten_files = [
        metadata
        for file_id, metadata in (all_injected_file_metadata or {}).items()
        if file_id not in surviving_file_ids
    ]
    if forgotten_files and token_counter:
        context.append(
            _create_file_tool_metadata_message(
                forgotten_files, token_counter, available_tool_names
            )
        )
    required_tokens = sum(message.token_count for message in context)
    required_tokens += system_prompt.token_count if system_prompt else 0
    required_tokens += reminder_message.token_count if reminder_message else 0
    if user_indices:
        required_tokens += count_message_replay_tokens(
            history[user_indices[-1]],
            image_files_replayed_as_markers=image_files_replayed_as_markers,
            token_counter=token_counter,
        )
    if required_tokens > available_tokens:
        raise ValueError(
            "Not enough tokens for the agent instructions, attached context, and latest user message."
        )
    result = [system_prompt] if system_prompt else []
    result.extend(history[:insertion_index])
    result.extend(context)
    result.extend(history[insertion_index:])
    if reminder_message:
        result.append(reminder_message)
    return result


def _create_file_tool_metadata_message(
    file_metadata: list[FileToolMetadata],
    token_counter: Callable[[str], int],
    available_tool_names: set[str] | None = None,
) -> ChatMessageSimple:
    """Build a lightweight metadata-only message listing files not held in context.

    Name only a tool this step actually received. FileReaderTool is attached
    only when the vector DB is disabled, and internal search can be absent even
    when it is enabled (persona, ``allowed_tool_ids``, or a disabled search
    usage setting). Naming a tool the model was never given makes it invent
    workarounds — it searches the web for the document or guesses the contents.

    Preference order is read_file, then internal search, then the python tool.
    read_file pages through a file directly; search retrieves from the indexed
    copy; the python tool is handed the files themselves, so prompt truncation
    does not take them away from it.

    The python tier applies only when every listed file actually reached
    ``chat_files_for_tools`` (see ``FileToolMetadata.staged_for_tools``) —
    summary-truncated files are listed for the LLM but never staged, so naming
    python for them would send the model after bytes it does not have. The
    notice also stops short of promising a path, because PythonTool normalizes
    and de-duplicates filenames at staging time and applies its own count and
    byte caps.

    An unreported tool set names no tool. Steps that offer none are common (a
    deep-research final report runs with no tools), and under-promising is the
    safe direction to fail in.
    """
    offered: set[str] = available_tool_names or set()
    if FILE_READER_TOOL_NAME in offered:
        lines: list[str] = [
            "You have access to the following files. Use the read_file tool to "
            "read sections of any file. You MUST pass the file_id UUID (not the "
            "filename) to read_file:"
        ]
        # The UUID is only meaningful to read_file, so it is listed only here.
        lines.extend(
            f'- file_id="{meta.file_id}" filename="{meta.filename}" (~{meta.approx_char_count:,} chars)'
            for meta in file_metadata
        )
        return _finalize_file_metadata_message(lines, token_counter)

    if SearchTool.NAME in offered:
        lines = [
            "These files are attached but too large to include in full. Their "
            "contents are indexed — use internal search to find the relevant "
            "passages. Do not guess them or search the web for them:"
        ]
    elif PythonTool.NAME in offered and all(
        meta.staged_for_tools for meta in file_metadata
    ):
        lines = [
            "These files are attached but too large to include in full. The "
            "python tool receives them — read them there, listing the working "
            "directory if a name does not resolve. Do not guess their contents "
            "or search the web for them:"
        ]
    else:
        lines = [
            "These files are attached but too large to include in full, and no "
            "tool here can read them. Do not guess their contents or search the "
            "web for them — say they are too large to read in this conversation:"
        ]
    lines.extend(
        f'- filename="{meta.filename}" (~{meta.approx_char_count:,} chars)'
        for meta in file_metadata
    )
    return _finalize_file_metadata_message(lines, token_counter)


def _finalize_file_metadata_message(
    lines: list[str],
    token_counter: Callable[[str], int],
) -> ChatMessageSimple:
    message_content = "\n".join(lines)
    return ChatMessageSimple(
        message=message_content,
        token_count=token_counter(message_content),
        message_type=MessageType.USER,
    )


def _create_context_files_message(
    context_files: ExtractedContextFiles,
    token_counter: Callable[[str], int] | None,  # noqa: ARG001
) -> ChatMessageSimple:
    """Convert context files to a ChatMessageSimple message.

    Format follows the README specification for document representation.
    """
    import json

    # Format as documents JSON as described in README
    documents_list = []
    for idx, file_text in enumerate(context_files.file_texts, start=1):
        title = (
            context_files.file_metadata[idx - 1].filename
            if idx - 1 < len(context_files.file_metadata)
            else None
        )
        entry: dict[str, Any] = {"document": idx}
        if title:
            entry["title"] = title
        entry["contents"] = file_text
        documents_list.append(entry)

    documents_json = json.dumps({"documents": documents_list}, indent=2)
    message_content = f"Here are some documents provided for context, they may not all be relevant:\n{documents_json}"

    # Use pre-calculated token count from context_files
    return ChatMessageSimple(
        message=message_content,
        token_count=context_files.total_token_count,
        message_type=MessageType.USER,
    )


def select_reminder_text(
    *,
    ran_image_gen: bool,
    just_ran_web_search: bool,
    has_open_url_tool: bool,
    out_of_cycles: bool,
    persona_task_prompt: str | None,
    include_citation_reminder: bool,
    include_file_reminder: bool,
) -> str | None:
    """Choose the reminder appended after a tool cycle.

    The open_url nudge is gated on the tool actually being available; otherwise
    the model is told to call a tool it doesn't have and leaks confusing
    "open_url is not available" replies.
    """
    if ran_image_gen:
        return IMAGE_GEN_REMINDER
    if just_ran_web_search and has_open_url_tool and not out_of_cycles:
        return OPEN_URL_REMINDER
    return build_reminder_message(
        reminder_text=persona_task_prompt,
        include_citation_reminder=include_citation_reminder,
        include_file_reminder=include_file_reminder,
        is_last_cycle=out_of_cycles,
    )


def tool_context_from_messages(
    messages: list[pm.ModelMessage],
) -> list[ChatMessageSimple]:
    """Supply text context to domain tools without rewriting native model history."""
    result: list[ChatMessageSimple] = []
    for message in messages:
        for part in message.parts:
            text: str | None = None
            kind = MessageType.ASSISTANT
            if isinstance(part, pm.UserPromptPart):
                text = (
                    part.content
                    if isinstance(part.content, str)
                    else "\n".join(
                        item for item in part.content if isinstance(item, str)
                    )
                )
                kind = MessageType.USER
            elif isinstance(part, pm.TextPart):
                text = part.content
            elif isinstance(part, pm.ToolReturnPart):
                text = part.model_response_str()
                kind = MessageType.TOOL_CALL_RESPONSE
            if text is not None:
                result.append(
                    ChatMessageSimple(message=text, token_count=0, message_type=kind)
                )
    return result


def run_chat_agent(
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
        "run_chat_agent",
        group_id=chat_session_id,
        metadata=ChatTraceMetadata(
            chat_session_id=chat_session_id,
            user_id=user_identity.user_id if user_identity else None,
        ).model_dump(),
    ):
        memory_tool = next(
            (tool for tool in tools if isinstance(tool, MemoryTool)), None
        )
        force_memory = memory_tool is not None and forced_tool_id == memory_tool.id
        if force_memory:
            forced_tool_id = None
        tools = [tool for tool in tools if not isinstance(tool, MemoryTool)]
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

        model_response = pm.ModelResponse(parts=[])
        pending_tool_calls: list[ToolCallKickoff] = []

        token_budget = resolve_chat_token_budget(llm)
        available_tokens = token_budget.input_tokens
        # When the model takes no image input, history images are replayed as
        # short text markers (translate_history_to_native_messages) — budget them
        # as markers too, not at their stored image token cost.
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
        citation_mapping: dict[int, str] = {}  # Maps citation_num -> document_id/URL

        # Fetch this in a short-lived session so the long-running stream loop does
        # not pin a connection just to keep read state alive.
        with get_session_with_current_tenant() as prompt_db_session:
            default_base_system_prompt: str = get_default_base_system_prompt(
                prompt_db_session
            )

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
        tool_state_lock = threading.Lock()
        citation_starts: dict[str, int] = {}
        tool_message_history = simple_chat_history
        llm_cycle_count = -1
        final_tools: list[Tool] = []

        native_history = translate_history_to_native_messages(
            simple_chat_history, llm.config
        )

        def prepare_step(messages: list[pm.ModelMessage]) -> NativeAgentRequest:
            nonlocal llm_cycle_count, forced_tool_id
            nonlocal tool_choice, final_tools, just_ran_web_search, tool_message_history
            conversation = [
                message
                for message in messages
                if not (message.metadata or {}).get("onyx_prompt")
            ]
            tool_message_history = tool_context_from_messages(conversation)
            just_ran_web_search = False if llm_cycle_count < 0 else just_ran_web_search
            # Handling tool calls based on cycle count and past cycle conditions
            llm_cycle_count += 1
            out_of_cycles = llm_cycle_count >= MAX_LLM_CYCLES - 1
            if force_memory and llm_cycle_count == 0:
                final_tools = []
                tool_choice = ToolChoiceOptions.REQUIRED
            elif forced_tool_id:
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
                        user_memory_context.without_memories()
                        if user_memory_context
                        else None
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
            surviving_file_ids = {
                (message.metadata or {}).get("onyx_file_id") for message in conversation
            }
            missing_files = {
                file_id: metadata
                for file_id, metadata in (all_injected_file_metadata or {}).items()
                if file_id not in surviving_file_ids
            }
            prompt_records = construct_message_history(
                system_prompt=system_prompt,
                custom_agent_prompt=custom_agent_prompt_msg,
                simple_chat_history=[],
                reminder_message=None,
                context_files=context_files,
                available_tokens=max(0, available_tokens - tool_token_budget),
                token_counter=token_counter,
                all_injected_file_metadata=missing_files,
                available_tool_names={tool.name for tool in final_tools},
            )
            prompt_messages = translate_history_to_native_messages(
                prompt_records, llm.config
            )
            for message in prompt_messages:
                message.metadata = {**(message.metadata or {}), "onyx_prompt": True}
            user_indices = [
                index
                for index, message in enumerate(conversation)
                if isinstance(message, pm.ModelRequest)
                and any(isinstance(part, pm.UserPromptPart) for part in message.parts)
            ]
            insertion = user_indices[-1] if user_indices else len(conversation)
            systems = [
                message
                for message in prompt_messages
                if isinstance(message, pm.ModelRequest)
                and any(isinstance(part, pm.SystemPromptPart) for part in message.parts)
            ]
            context = [message for message in prompt_messages if message not in systems]
            prepared_history = [
                *systems,
                *conversation[:insertion],
                *context,
                *conversation[insertion:],
            ]
            if reminder_msg:
                reminders = translate_history_to_native_messages(
                    [reminder_msg], llm.config
                )
                for message in reminders:
                    message.metadata = {
                        **(message.metadata or {}),
                        "onyx_prompt": True,
                        "onyx_reminder": True,
                    }
                prepared_history.extend(reminders)
            max_output_tokens = token_budget.output_allowance(
                estimated_input_tokens=min(
                    available_tokens,
                    tool_token_budget
                    + estimate_token_count(prepared_history, token_counter),
                )
            )
            just_ran_web_search = False
            return NativeAgentRequest(
                messages=prepared_history,
                settings=llm.model_settings(
                    reasoning_effort=reasoning_effort,
                    max_tokens=max_output_tokens,
                    user_identity=user_identity,
                    tool_choice=tool_choice,
                ),
                allow_tools=tool_choice != ToolChoiceOptions.NONE,
                tools=[
                    ToolDefinition(
                        name=definition["function"]["name"],
                        description=definition["function"].get("description"),
                        parameters_json_schema=definition["function"]["parameters"],
                    )
                    for definition in (tool.tool_definition() for tool in final_tools)
                ],
            )

        def finalize_step(response: pm.ModelResponse) -> None:
            nonlocal model_response, pending_tool_calls, reasoning_cycles
            model_response = response
            reasoning = response.thinking
            answer = response.text
            if reasoning:
                reasoning_cycles += 1
            turn_index = llm_cycle_count + reasoning_cycles
            native_calls = [
                part for part in response.parts if isinstance(part, pm.ToolCallPart)
            ]
            tab_offset = 1 if answer else 0
            first_citation = citation_processor.get_next_citation_number()
            citation_starts.clear()
            citation_starts.update(
                {
                    call.tool_call_id: first_citation + index * 100
                    for index, call in enumerate(native_calls)
                }
            )
            if len(native_calls) > 1:
                emitter.emit(
                    Packet(
                        placement=Placement(turn_index=turn_index),
                        obj=TopLevelBranching(num_parallel_branches=len(native_calls)),
                    )
                )
            pending_tool_calls = [
                ToolCallKickoff(
                    tool_call_id=part.tool_call_id,
                    tool_name=part.tool_name,
                    tool_args=part.args_as_dict(),
                    placement=Placement(
                        turn_index=turn_index, tab_index=index + tab_offset
                    ),
                )
                for index, part in enumerate(native_calls)
            ]
            if not model_response.text and not model_response.tool_calls:
                raise _build_empty_llm_response_error(llm, model_response, tool_choice)
            if state_container:
                state_container.set_citation_mapping(citation_processor.citation_to_doc)

        async def execute_tool(
            context: RunContext[None], native_call: pm.ToolCallPart
        ) -> str:
            nonlocal citation_mapping, just_ran_web_search, has_called_search_tool
            nonlocal code_interpreter_file_generated, gathered_documents
            nonlocal ran_image_gen, should_cite_documents
            # Run the LLM selected tools, there is some more logic here than a simple execution
            # each tool might have custom logic here
            tool_responses: list[ToolResponse] = []
            original_call = next(
                call
                for call in pending_tool_calls
                if call.tool_call_id == native_call.tool_call_id
            )
            tool_calls = [
                original_call.model_copy(
                    update={"tool_args": native_call.args_as_dict()}
                )
            ]

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

            with tool_state_lock:
                local_citations = dict(citation_mapping)
                skip_query_expansion = has_called_search_tool
                if native_call.tool_name == SearchTool.NAME:
                    has_called_search_tool = True
                files_snapshot = list(chat_files)
                snippets_snapshot = extract_url_snippet_map(gathered_documents or [])
            tool_response = await run_tool_call_async(
                context=context,
                tool_call=tool_calls[0],
                tools=final_tools,
                message_history=tool_message_history,
                user_memory_context=user_memory_context,
                user_info=None,  # TODO, this is part of memories right now, might want to separate it out
                citation_mapping=local_citations,
                next_citation_num=citation_starts[native_call.tool_call_id],
                skip_search_query_expansion=skip_query_expansion,
                chat_files=files_snapshot,
                url_snippet_map=snippets_snapshot,
                inject_memories_in_prompt=inject_memories_in_prompt,
            )
            check_tool_run_active()
            tool_responses = [tool_response]

            if not tool_responses:
                return "Tool execution failed. Try again."

            with tool_state_lock:
                check_tool_run_active()
                if isinstance(tool_response.rich_response, SearchDocsResponse):
                    citation_mapping.update(
                        tool_response.rich_response.citation_mapping or {}
                    )
                for tool_response in tool_responses:
                    # The domain runner attaches the original native tool call.
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
                        tool_response.rich_response.tool_result,
                        CustomToolUserFileSnapshot,
                    ):
                        generated_file_ids = (
                            tool_response.rich_response.tool_result.file_ids or None
                        )

                    if isinstance(tool_response.rich_response, CustomToolCallSummary):
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
                        reasoning_tokens=model_response.thinking,  # All tool calls from this loop share the same reasoning
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

                # Certain tools do not allow further actions, force the LLM wrap up on the next cycle
                if any(
                    tool.tool_name in STOPPING_TOOLS_NAMES
                    for tool in pending_tool_calls
                ):
                    ran_image_gen = True

                if model_response.tool_calls and any(
                    tool.tool_name in CITEABLE_TOOLS_NAMES
                    for tool in pending_tool_calls
                ):
                    # As long as 1 tool with citeable documents is called at any point, we ask the LLM to try to cite
                    should_cite_documents = True

            return tool_responses[0].llm_facing_response

        memory_capability = (
            create_memory_capability(
                user_id=user_memory_context.user_id,
                tenant_id=get_current_tenant_id(),
                inject_memory=inject_memories_in_prompt,
                writable=memory_tool is not None,
                tool_id=memory_tool.id if memory_tool else None,
                state_container=state_container,
                placement=lambda native_call: next(
                    call.placement
                    for call in pending_tool_calls
                    if call.tool_call_id == native_call.tool_call_id
                ),
            )
            if user_memory_context and user_memory_context.user_id
            else None
        )

        run_native_agent(
            llm=llm,
            prepare_step=prepare_step,
            finalize_step=finalize_step,
            emitter=emitter,
            state_container=state_container,
            placement=lambda: Placement(turn_index=llm_cycle_count + reasoning_cycles),
            message_history=native_history,
            tokenizer=token_counter,
            capabilities=[memory_capability] if memory_capability else None,
            citation_processor=citation_processor,
            final_documents=lambda: gathered_documents,
            elapsed_seconds=lambda: time.monotonic() - loop_start_time,
            execute_tool_async=execute_tool,
            tool_definitions=[tool.tool_definition() for tool in tools],
            max_requests=MAX_LLM_CYCLES,
        )

        if not model_response.text and not model_response.tool_calls:
            raise _build_empty_llm_response_error(
                llm=llm,
                response=model_response,
                tool_choice=tool_choice,
            )

        if not model_response.text:
            raise RuntimeError(
                "The LLM did not return a final answer after tool execution. "
                "Typically this indicates invalid tool-call output, a model/provider mismatch, "
                "or serving API misconfiguration."
            )

        emitter.emit(
            Packet(
                placement=Placement(turn_index=llm_cycle_count + reasoning_cycles),
                obj=OverallStop(type="stop"),
            )
        )
