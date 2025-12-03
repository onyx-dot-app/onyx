import json
from collections.abc import Callable
from collections.abc import Mapping
from collections.abc import Sequence
from typing import Any
from typing import cast

from sqlalchemy.orm import Session

from onyx.chat.chat_state import ChatStateContainer
from onyx.chat.citation_processor import DynamicCitationProcessor
from onyx.chat.emitter import Emitter
from onyx.chat.models import ChatMessageSimple
from onyx.chat.models import ExtractedProjectFiles
from onyx.chat.models import LlmStepResult
from onyx.chat.models import ProjectFileMetadata
from onyx.chat.prompt_builder.answer_prompt_builder import build_reminder_message
from onyx.chat.prompt_builder.answer_prompt_builder import build_system_prompt
from onyx.chat.prompt_builder.answer_prompt_builder import (
    get_default_base_system_prompt,
)
from onyx.configs.constants import DocumentSource
from onyx.configs.constants import MessageType
from onyx.context.search.models import SearchDoc
from onyx.context.search.models import SearchDocsResponse
from onyx.db.models import Persona
from onyx.file_store.models import ChatFileType
from onyx.llm.interfaces import LanguageModelInput
from onyx.llm.interfaces import LLM
from onyx.llm.interfaces import ToolChoiceOptions
from onyx.llm.message_types import AssistantMessage
from onyx.llm.message_types import ChatCompletionMessage
from onyx.llm.message_types import ImageContentPart
from onyx.llm.message_types import SystemMessage
from onyx.llm.message_types import TextContentPart
from onyx.llm.message_types import ToolCall
from onyx.llm.message_types import ToolMessage
from onyx.llm.message_types import UserMessageWithParts
from onyx.llm.message_types import UserMessageWithText
from onyx.llm.utils import model_needs_formatting_reenabled
from onyx.prompts.chat_prompts import IMAGE_GEN_REMINDER
from onyx.prompts.chat_prompts import OPEN_URL_REMINDER
from onyx.server.query_and_chat.streaming_models import AgentResponseDelta
from onyx.server.query_and_chat.streaming_models import AgentResponseStart
from onyx.server.query_and_chat.streaming_models import CitationInfo
from onyx.server.query_and_chat.streaming_models import OverallStop
from onyx.server.query_and_chat.streaming_models import Packet
from onyx.server.query_and_chat.streaming_models import ReasoningDelta
from onyx.server.query_and_chat.streaming_models import ReasoningDone
from onyx.server.query_and_chat.streaming_models import ReasoningStart
from onyx.tools.models import ToolCallInfo
from onyx.tools.models import ToolCallKickoff
from onyx.tools.models import ToolResponse
from onyx.tools.tool import Tool
from onyx.tools.tool_implementations.images.image_generation_tool import (
    ImageGenerationTool,
)
from onyx.tools.tool_implementations.images.models import (
    FinalImageGenerationResponse,
)
from onyx.tools.tool_implementations.open_url.open_url_tool import OpenURLTool
from onyx.tools.tool_implementations.search.search_tool import SearchTool
from onyx.tools.tool_implementations.web_search.web_search_tool import WebSearchTool
from onyx.tools.tool_runner import run_tool_calls
from onyx.tracing.framework.create import generation_span
from onyx.tracing.framework.create import trace
from onyx.utils.b64 import get_image_type_from_bytes
from onyx.utils.logger import setup_logger
from shared_configs.contextvars import get_current_tenant_id

logger = setup_logger()

# Hardcoded oppinionated value, might breaks down to something like:
# Cycle 1: Calls web_search for something
# Cycle 2: Calls open_url for some results
# Cycle 3: Calls web_search for some other aspect of the question
# Cycle 4: Calls open_url for some results
# Cycle 5: Maybe call open_url for some additional results or because last set failed
# Cycle 6: No more tools available, forced to answer
MAX_LLM_CYCLES = 6

TOOL_CALL_MSG_FUNC_NAME = "function_name"
TOOL_CALL_MSG_ARGUMENTS = "arguments"


def _build_project_file_citation_mapping(
    project_file_metadata: list[ProjectFileMetadata],
    starting_citation_num: int = 1,
) -> dict[int, SearchDoc]:
    """Build citation mapping for project files.

    Converts project file metadata into SearchDoc objects that can be cited.
    Citation numbers start from the provided starting number.

    Args:
        project_file_metadata: List of project file metadata
        starting_citation_num: Starting citation number (default: 1)

    Returns:
        Dictionary mapping citation numbers to SearchDoc objects
    """
    citation_mapping: dict[int, SearchDoc] = {}

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


def construct_message_history(
    system_prompt: ChatMessageSimple,
    custom_agent_prompt: ChatMessageSimple | None,
    simple_chat_history: list[ChatMessageSimple],
    reminder_message: ChatMessageSimple | None,
    project_files: ExtractedProjectFiles,
    available_tokens: int,
) -> list[ChatMessageSimple]:
    history_token_budget = available_tokens
    history_token_budget -= system_prompt.token_count
    history_token_budget -= (
        custom_agent_prompt.token_count if custom_agent_prompt else 0
    )
    history_token_budget -= project_files.total_token_count
    history_token_budget -= reminder_message.token_count if reminder_message else 0

    if history_token_budget < 0:
        raise ValueError("Not enough tokens available to construct message history")

    # If no history, build minimal context
    if not simple_chat_history:
        result = [system_prompt]
        if custom_agent_prompt:
            result.append(custom_agent_prompt)
        if project_files.project_file_texts:
            project_message = _create_project_files_message(
                project_files, tokenizer_func=None
            )
            result.append(project_message)
        if reminder_message:
            result.append(reminder_message)
        return result

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

    # Truncate history_before_last_user from the top to fit in remaining budget
    truncated_history_before: list[ChatMessageSimple] = []
    current_token_count = 0

    for msg in reversed(history_before_last_user):
        if current_token_count + msg.token_count <= remaining_budget:
            truncated_history_before.insert(0, msg)
            current_token_count += msg.token_count
        else:
            # Can't fit this message, stop truncating
            break

    # Attach project images to the last user message
    if project_files.project_image_files:
        existing_images = last_user_message.image_files or []
        last_user_message = ChatMessageSimple(
            message=last_user_message.message,
            token_count=last_user_message.token_count,
            message_type=last_user_message.message_type,
            image_files=existing_images + project_files.project_image_files,
        )

    # Build the final message list according to README ordering:
    # [system], [history_before_last_user], [custom_agent], [project_files],
    # [last_user_message], [messages_after_last_user], [reminder]
    result = [system_prompt]

    # 1. Add truncated history before last user message
    result.extend(truncated_history_before)

    # 2. Add custom agent prompt (inserted before last user message)
    if custom_agent_prompt:
        result.append(custom_agent_prompt)

    # 3. Add project files message (inserted before last user message)
    if project_files.project_file_texts:
        project_message = _create_project_files_message(
            project_files, tokenizer_func=None
        )
        result.append(project_message)

    # 4. Add last user message (with project images attached)
    result.append(last_user_message)

    # 5. Add messages after last user message (tool calls, responses, etc.)
    result.extend(messages_after_last_user)

    # 6. Add reminder message at the very end
    if reminder_message:
        result.append(reminder_message)

    return result


def _create_project_files_message(
    project_files: ExtractedProjectFiles,
    tokenizer_func: Callable[[str], list[int]] | None,
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


def translate_history_to_llm_format(
    history: list[ChatMessageSimple],
) -> LanguageModelInput:
    """Convert a list of ChatMessageSimple to LanguageModelInput format.

    Converts ChatMessageSimple messages to ChatCompletionMessage format,
    handling different message types and image files for multimodal support.
    """
    messages: list[ChatCompletionMessage] = []

    for msg in history:
        if msg.message_type == MessageType.SYSTEM:
            system_msg: SystemMessage = {
                "role": "system",
                "content": msg.message,
            }
            messages.append(system_msg)

        elif msg.message_type == MessageType.USER:
            # Handle user messages with potential images
            if msg.image_files:
                # Build content parts: text + images
                content_parts: list[TextContentPart | ImageContentPart] = [
                    {"type": "text", "text": msg.message}
                ]

                # Add image parts
                for img_file in msg.image_files:
                    if img_file.file_type == ChatFileType.IMAGE:
                        try:
                            image_type = get_image_type_from_bytes(img_file.content)
                            base64_data = img_file.to_base64()
                            image_url = f"data:{image_type};base64,{base64_data}"

                            image_part: ImageContentPart = {
                                "type": "image_url",
                                "image_url": {"url": image_url},
                            }
                            content_parts.append(image_part)
                        except Exception as e:
                            logger.warning(
                                f"Failed to process image file {img_file.file_id}: {e}. "
                                "Skipping image."
                            )

                user_msg_with_parts: UserMessageWithParts = {
                    "role": "user",
                    "content": content_parts,
                }
                messages.append(user_msg_with_parts)
            else:
                # Simple text-only user message
                user_msg_text: UserMessageWithText = {
                    "role": "user",
                    "content": msg.message,
                }
                messages.append(user_msg_text)

        elif msg.message_type == MessageType.ASSISTANT:
            assistant_msg: AssistantMessage = {
                "role": "assistant",
                "content": msg.message or None,
            }
            messages.append(assistant_msg)

        elif msg.message_type == MessageType.TOOL_CALL:
            # Tool calls are represented as Assistant Messages with tool_calls field
            # Try to reconstruct tool call structure if we have tool_call_id
            tool_calls: list[ToolCall] = []
            if msg.tool_call_id:
                try:
                    # Parse the message content (which should contain function_name and arguments)
                    tool_call_data = json.loads(msg.message) if msg.message else {}

                    if (
                        isinstance(tool_call_data, dict)
                        and TOOL_CALL_MSG_FUNC_NAME in tool_call_data
                    ):
                        function_name = tool_call_data.get(
                            TOOL_CALL_MSG_FUNC_NAME, "unknown"
                        )
                        tool_args = tool_call_data.get(TOOL_CALL_MSG_ARGUMENTS, {})
                    else:
                        function_name = "unknown"
                        tool_args = (
                            tool_call_data if isinstance(tool_call_data, dict) else {}
                        )

                    # NOTE: if the model is trained on a different tool call format, this may slightly interfere
                    # with the future tool calls, if it doesn't look like this. Almost certainly not a big deal.
                    tool_call: ToolCall = {
                        "id": msg.tool_call_id,
                        "type": "function",
                        "function": {
                            "name": function_name,
                            "arguments": json.dumps(tool_args) if tool_args else "{}",
                        },
                    }
                    tool_calls.append(tool_call)
                except (json.JSONDecodeError, ValueError) as e:
                    logger.warning(
                        f"Failed to parse tool call data for tool_call_id {msg.tool_call_id}: {e}. "
                        "Including as content-only message."
                    )

            assistant_msg_with_tool: AssistantMessage = {
                "role": "assistant",
                "content": None,  # The tool call is parsed, doesn't need to be duplicated in the content
            }
            if tool_calls:
                assistant_msg_with_tool["tool_calls"] = tool_calls
            messages.append(assistant_msg_with_tool)

        elif msg.message_type == MessageType.TOOL_CALL_RESPONSE:
            if not msg.tool_call_id:
                raise ValueError(
                    f"Tool call response message encountered but tool_call_id is not available. Message: {msg}"
                )

            tool_msg: ToolMessage = {
                "role": "tool",
                "content": msg.message,
                "tool_call_id": msg.tool_call_id,
            }
            messages.append(tool_msg)

        else:
            logger.warning(
                f"Unknown message type {msg.message_type} in history. Skipping message."
            )

    return messages


def _format_message_history_for_logging(
    message_history: LanguageModelInput,
) -> str:
    """Format message history for logging, with special handling for tool calls.

    Tool calls are formatted as JSON with 4-space indentation for readability.
    """
    formatted_lines = []

    separator = "================================================"

    # Handle string input
    if isinstance(message_history, str):
        formatted_lines.append("Message [string]:")
        formatted_lines.append(separator)
        formatted_lines.append(f"{message_history}")
        return "\n".join(formatted_lines)

    # Handle sequence of messages
    for i, msg in enumerate(message_history):
        # Type guard: ensure msg is a dict-like object (TypedDict)
        if not isinstance(msg, dict):
            formatted_lines.append(f"Message {i + 1} [unknown]:")
            formatted_lines.append(separator)
            formatted_lines.append(f"{msg}")
            if i < len(message_history) - 1:
                formatted_lines.append(separator)
            continue

        role = msg.get("role", "unknown")
        formatted_lines.append(f"Message {i + 1} [{role}]:")
        formatted_lines.append(separator)

        if role == "system":
            content = msg.get("content", "")
            if isinstance(content, str):
                formatted_lines.append(f"{content}")

        elif role == "user":
            content = msg.get("content", "")
            if isinstance(content, str):
                formatted_lines.append(f"{content}")
            elif isinstance(content, list):
                # Handle multimodal content (text + images)
                for part in content:
                    if isinstance(part, dict):
                        part_type = part.get("type")
                        if part_type == "text":
                            text = part.get("text", "")
                            if isinstance(text, str):
                                formatted_lines.append(f"{text}")
                        elif part_type == "image_url":
                            image_url_dict = part.get("image_url")
                            if isinstance(image_url_dict, dict):
                                url = image_url_dict.get("url", "")
                                if isinstance(url, str):
                                    formatted_lines.append(f"[Image: {url[:50]}...]")

        elif role == "assistant":
            content = msg.get("content")
            if content and isinstance(content, str):
                formatted_lines.append(f"{content}")

            tool_calls = msg.get("tool_calls")
            if tool_calls and isinstance(tool_calls, list):
                formatted_lines.append("Tool calls:")
                for tool_call in tool_calls:
                    if isinstance(tool_call, dict):
                        tool_call_dict: dict[str, Any] = {}
                        tool_call_id = tool_call.get("id")
                        tool_call_type = tool_call.get("type")
                        function_dict = tool_call.get("function")

                        if tool_call_id:
                            tool_call_dict["id"] = tool_call_id
                        if tool_call_type:
                            tool_call_dict["type"] = tool_call_type
                        if isinstance(function_dict, dict):
                            tool_call_dict["function"] = {
                                "name": function_dict.get("name", ""),
                                "arguments": function_dict.get("arguments", ""),
                            }

                        tool_call_json = json.dumps(tool_call_dict, indent=4)
                        formatted_lines.append(tool_call_json)

        elif role == "tool":
            content = msg.get("content", "")
            tool_call_id = msg.get("tool_call_id", "")
            if isinstance(content, str) and isinstance(tool_call_id, str):
                formatted_lines.append(f"Tool call ID: {tool_call_id}")
                formatted_lines.append(f"Response: {content}")

        # Add separator before next message (or at end)
        if i < len(message_history) - 1:
            formatted_lines.append(separator)

    return "\n".join(formatted_lines)


def run_llm_step(
    history: list[ChatMessageSimple],
    tool_definitions: list[dict],
    tool_choice: ToolChoiceOptions,
    emitter: Emitter,
    llm: LLM,
    turn_index: int,
    citation_processor: DynamicCitationProcessor,
    state_container: ChatStateContainer,
    final_documents: list[SearchDoc] | None = None,
) -> tuple[LlmStepResult, int]:
    # The second return value is for the turn index because reasoning counts on the frontend as a turn
    # TODO this is maybe ok but does not align well with the backend logic too well
    llm_msg_history = translate_history_to_llm_format(history)

    # Uncomment the line below to log the entire message history to the console
    # logger.info(
    #     f"Message history:\n{_format_message_history_for_logging(llm_msg_history)}"
    # )

    id_to_tool_call_map: dict[int, dict[str, Any]] = {}
    reasoning_start = False
    answer_start = False
    accumulated_reasoning = ""
    accumulated_answer = ""

    with generation_span(
        model=llm.config.model_name,
        model_config={
            "base_url": str(llm.config.api_base or ""),
            "model_impl": "litellm",
        },
    ) as span_generation:
        span_generation.span_data.input = cast(
            Sequence[Mapping[str, Any]], llm_msg_history
        )
        for packet in llm.stream(
            prompt=llm_msg_history,
            tools=tool_definitions,
            tool_choice=tool_choice,
            structured_response_format=None,  # TODO
        ):
            if packet.usage:
                usage = packet.usage
                span_generation.span_data.usage = {
                    "input_tokens": usage.prompt_tokens,
                    "output_tokens": usage.completion_tokens,
                    "cache_read_input_tokens": usage.cache_read_input_tokens,
                    "cache_creation_input_tokens": usage.cache_creation_input_tokens,
                }
            delta = packet.choice.delta

            # Should only happen once, frontend does not expect multiple
            # ReasoningStart or ReasoningDone packets.
            if delta.reasoning_content:
                accumulated_reasoning += delta.reasoning_content
                # Save reasoning incrementally to state container
                state_container.set_reasoning_tokens(accumulated_reasoning)
                if not reasoning_start:
                    emitter.emit(
                        Packet(
                            turn_index=turn_index,
                            obj=ReasoningStart(),
                        )
                    )
                emitter.emit(
                    Packet(
                        turn_index=turn_index,
                        obj=ReasoningDelta(reasoning=delta.reasoning_content),
                    )
                )
                reasoning_start = True

            if delta.content:
                if reasoning_start:
                    emitter.emit(
                        Packet(
                            turn_index=turn_index,
                            obj=ReasoningDone(),
                        )
                    )
                    turn_index += 1
                    reasoning_start = False

                if not answer_start:
                    emitter.emit(
                        Packet(
                            turn_index=turn_index,
                            obj=AgentResponseStart(
                                final_documents=final_documents,
                            ),
                        )
                    )
                    answer_start = True

                for result in citation_processor.process_token(delta.content):
                    if isinstance(result, str):
                        accumulated_answer += result
                        # Save answer incrementally to state container
                        state_container.set_answer_tokens(accumulated_answer)
                        emitter.emit(
                            Packet(
                                turn_index=turn_index,
                                obj=AgentResponseDelta(content=result),
                            )
                        )
                    elif isinstance(result, CitationInfo):
                        emitter.emit(
                            Packet(
                                turn_index=turn_index,
                                obj=result,
                            )
                        )

            if delta.tool_calls:
                if reasoning_start:
                    emitter.emit(
                        Packet(
                            turn_index=turn_index,
                            obj=ReasoningDone(),
                        )
                    )
                    turn_index += 1
                    reasoning_start = False

                for tool_call_delta in delta.tool_calls:
                    _update_tool_call_with_delta(id_to_tool_call_map, tool_call_delta)
        span_generation.span_data.output = [
            {"role": "assistant", "content": accumulated_answer}
        ]
    # Close reasoning block if still open (stream ended with reasoning content)
    if reasoning_start:
        emitter.emit(
            Packet(
                turn_index=turn_index,
                obj=ReasoningDone(),
            )
        )
        turn_index += 1

    # Flush any remaining content from citation processor
    if citation_processor:
        for result in citation_processor.process_token(None):
            if isinstance(result, str):
                accumulated_answer += result
                # Save answer incrementally to state container
                state_container.set_answer_tokens(accumulated_answer)
                emitter.emit(
                    Packet(
                        turn_index=turn_index,
                        obj=AgentResponseDelta(content=result),
                    )
                )
            elif isinstance(result, CitationInfo):
                emitter.emit(
                    Packet(
                        turn_index=turn_index,
                        obj=result,
                    )
                )

    # Note: Content (AgentResponseDelta) doesn't need an explicit end packet - OverallStop handles it
    # Tool calls are handled by tool execution code and emit their own packets (e.g., SectionEnd)

    # Convert tool calls from map to ToolCallKickoff list
    tool_calls: list[ToolCallKickoff] = []
    for tool_call_data in id_to_tool_call_map.values():
        if tool_call_data["id"] and tool_call_data["name"]:
            try:
                # Parse arguments JSON string to dict
                tool_args = (
                    json.loads(tool_call_data["arguments"])
                    if tool_call_data["arguments"]
                    else {}
                )
            except json.JSONDecodeError:
                # If parsing fails, try empty dict, most tools would fail though
                logger.error(
                    f"Failed to parse tool call arguments: {tool_call_data['arguments']}"
                )
                tool_args = {}

            tool_calls.append(
                ToolCallKickoff(
                    tool_call_id=tool_call_data["id"],
                    tool_name=tool_call_data["name"],
                    tool_args=tool_args,
                )
            )

    # Uncomment the lines below to log the LLM call results
    # logger.debug(f"Accumulated reasoning: {accumulated_reasoning}")
    # logger.debug(f"Accumulated answer: {accumulated_answer}")
    if tool_calls:
        tool_calls_str = "\n".join(
            f"  - {tc.tool_name}: {json.dumps(tc.tool_args, indent=4)}"
            for tc in tool_calls
        )
        logger.debug(f"Tool calls:\n{tool_calls_str}")
    else:
        logger.debug("Tool calls: []")

    return (
        LlmStepResult(
            reasoning=accumulated_reasoning if accumulated_reasoning else None,
            answer=accumulated_answer if accumulated_answer else None,
            tool_calls=tool_calls if tool_calls else None,
        ),
        turn_index,
    )


def _update_tool_call_with_delta(
    tool_calls_in_progress: dict[int, dict[str, Any]],
    tool_call_delta: Any,
) -> None:
    index = tool_call_delta.index

    if index not in tool_calls_in_progress:
        tool_calls_in_progress[index] = {
            "id": None,
            "name": None,
            "arguments": "",
        }

    if tool_call_delta.id:
        tool_calls_in_progress[index]["id"] = tool_call_delta.id

    if tool_call_delta.function:
        if tool_call_delta.function.name:
            tool_calls_in_progress[index]["name"] = tool_call_delta.function.name

        if tool_call_delta.function.arguments:
            tool_calls_in_progress[index][
                "arguments"
            ] += tool_call_delta.function.arguments


def run_llm_loop(
    emitter: Emitter,
    state_container: ChatStateContainer,
    simple_chat_history: list[ChatMessageSimple],
    tools: list[Tool],
    custom_agent_prompt: str | None,
    project_files: ExtractedProjectFiles,
    persona: Persona | None,
    memories: list[str] | None,
    llm: LLM,
    tokenizer_func: Callable[[str], list[int]],
    db_session: Session,
    forced_tool_id: int | None = None,
) -> None:
    with trace("run_llm_loop", metadata={"tenant_id": get_current_tenant_id()}):
        # Fix some LiteLLM issues,
        from onyx.llm.litellm_singleton.config import (
            initialize_litellm,
        )  # Here for lazy load LiteLLM

        initialize_litellm()

        stopping_tools_names: list[str] = [ImageGenerationTool.NAME]
        citeable_tools_names: list[str] = [
            SearchTool.NAME,
            WebSearchTool.NAME,
            OpenURLTool.NAME,
        ]

        # Initialize citation processor for handling citations dynamically
        citation_processor = DynamicCitationProcessor()

        # Add project file citation mappings if project files are present
        project_citation_mapping: dict[int, SearchDoc] = {}
        if project_files.project_file_metadata:
            project_citation_mapping = _build_project_file_citation_mapping(
                project_files.project_file_metadata
            )
            citation_processor.update_citation_mapping(project_citation_mapping)

        llm_step_result: LlmStepResult | None = None

        # Pass the total budget to construct_message_history, which will handle token allocation
        available_tokens = llm.config.max_input_tokens
        tool_choice: ToolChoiceOptions = "auto"
        collected_tool_calls: list[ToolCallInfo] = []
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
        citation_mapping: dict[int, str] = {}  # Maps citation_num -> document_id/URL

        current_tool_call_index = (
            0  # TODO: just use the cycle count after parallel tool calls are supported
        )

        for llm_cycle_count in range(MAX_LLM_CYCLES):

            if forced_tool_id:
                # Needs to be just the single one because the "required" currently doesn't have a specified tool, just a binary
                final_tools = [tool for tool in tools if tool.id == forced_tool_id]
                if not final_tools:
                    raise ValueError(f"Tool {forced_tool_id} not found in tools")
                tool_choice = "required"
                forced_tool_id = None
            elif llm_cycle_count == MAX_LLM_CYCLES - 1 or ran_image_gen:
                # Last cycle, no tools allowed, just answer!
                tool_choice = "none"
                final_tools = []
            else:
                tool_choice = "auto"
                final_tools = tools

            # The section below calculates the available tokens for history a bit more accurately
            # now that project files are loaded in.
            if persona and persona.replace_base_system_prompt and persona.system_prompt:
                # Handles the case where user has checked off the "Replace base system prompt" checkbox
                system_prompt = ChatMessageSimple(
                    message=persona.system_prompt,
                    token_count=len(tokenizer_func(persona.system_prompt)),
                    message_type=MessageType.SYSTEM,
                )
                custom_agent_prompt_msg = None
            else:
                # System message and custom agent message are both included.
                open_ai_formatting_enabled = model_needs_formatting_reenabled(
                    llm.config.model_name
                )

                system_prompt_str = build_system_prompt(
                    base_system_prompt=get_default_base_system_prompt(db_session),
                    datetime_aware=persona.datetime_aware if persona else True,
                    memories=memories,
                    tools=tools,
                    should_cite_documents=should_cite_documents
                    or always_cite_documents,
                    open_ai_formatting_enabled=open_ai_formatting_enabled,
                )
                system_prompt = ChatMessageSimple(
                    message=system_prompt_str,
                    token_count=len(tokenizer_func(system_prompt_str)),
                    message_type=MessageType.SYSTEM,
                )

                custom_agent_prompt_msg = (
                    ChatMessageSimple(
                        message=custom_agent_prompt,
                        token_count=len(tokenizer_func(custom_agent_prompt)),
                        message_type=MessageType.USER,
                    )
                    if custom_agent_prompt
                    else None
                )

            reminder_message_text: str | None
            if ran_image_gen:
                # Some models are trained to give back images to the user for some similar tool
                # This is to prevent it generating things like:
                # [Cute Cat](attachment://a_cute_cat_sitting_playfully.png)
                reminder_message_text = IMAGE_GEN_REMINDER
            elif just_ran_web_search:
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
                )

            reminder_msg = (
                ChatMessageSimple(
                    message=reminder_message_text,
                    token_count=len(tokenizer_func(reminder_message_text)),
                    message_type=MessageType.USER,
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
            )

            # This calls the LLM, passes in the emitter which can collect packets like reasoning, answers, etc.
            # It also pre-processes the tool calls in preparation for running them
            llm_step_result, current_tool_call_index = run_llm_step(
                history=truncated_message_history,
                tool_definitions=[tool.tool_definition() for tool in final_tools],
                tool_choice=tool_choice,
                emitter=emitter,
                llm=llm,
                turn_index=current_tool_call_index,
                citation_processor=citation_processor,
                state_container=state_container,
                # The rich docs representation is passed in so that when yielding the answer, it can also
                # immediately yield the full set of found documents. This gives us the option to show the
                # final set of documents immediately if desired.
                final_documents=gathered_documents,
            )

            # Save citation mapping after each LLM step for incremental state updates
            state_container.set_citation_mapping(citation_processor.citation_to_doc)

            # Run the LLM selected tools, there is some more logic here than a simple execution
            # each tool might have custom logic here
            tool_responses: list[ToolResponse] = []
            tool_calls = llm_step_result.tool_calls or []

            just_ran_web_search = False
            for tool_call in tool_calls:
                # TODO replace the [tool_call] with the list of tool calls once parallel tool calls are supported
                tool_responses, citation_mapping = run_tool_calls(
                    tool_calls=[tool_call],
                    tools=final_tools,
                    turn_index=current_tool_call_index,
                    message_history=truncated_message_history,
                    memories=memories,
                    user_info=None,  # TODO, this is part of memories right now, might want to separate it out
                    citation_mapping=citation_mapping,
                    citation_processor=citation_processor,
                )

                # Build a mapping of tool names to tool objects for getting tool_id
                tools_by_name = {tool.name: tool for tool in final_tools}

                # Add the results to the chat history, note that even if the tools were run in parallel, this isn't supported
                # as all the LLM APIs require linear history, so these will just be included sequentially
                for tool_call, tool_response in zip([tool_call], tool_responses):
                    # Get the tool object to retrieve tool_id
                    tool = tools_by_name.get(tool_call.tool_name)
                    if not tool:
                        raise ValueError(
                            f"Tool '{tool_call.tool_name}' not found in tools list"
                        )

                    # Collect tool call info with reasoning tokens from this LLM step
                    # All tool calls from the same loop iteration share the same reasoning tokens

                    # Extract search_docs if this is a search tool response
                    search_docs = None
                    if isinstance(tool_response.rich_response, SearchDocsResponse):
                        search_docs = tool_response.rich_response.search_docs
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

                    tool_call_info = ToolCallInfo(
                        parent_tool_call_id=None,  # Top-level tool calls are attached to the chat message
                        turn_index=current_tool_call_index,
                        tool_name=tool_call.tool_name,
                        tool_call_id=tool_call.tool_call_id,
                        tool_id=tool.id,
                        reasoning_tokens=llm_step_result.reasoning,  # All tool calls from this loop share the same reasoning
                        tool_call_arguments=tool_call.tool_args,
                        tool_call_response=tool_response.llm_facing_response,
                        search_docs=search_docs,
                        generated_images=generated_images,
                    )
                    collected_tool_calls.append(tool_call_info)
                    # Add to state container for partial save support
                    state_container.add_tool_call(tool_call_info)

                    # Store tool call with function name and arguments in separate layers
                    tool_call_data = {
                        TOOL_CALL_MSG_FUNC_NAME: tool_call.tool_name,
                        TOOL_CALL_MSG_ARGUMENTS: tool_call.tool_args,
                    }
                    tool_call_message = json.dumps(tool_call_data)
                    tool_call_token_count = len(tokenizer_func(tool_call_message))

                    tool_call_msg = ChatMessageSimple(
                        message=tool_call_message,
                        token_count=tool_call_token_count,
                        message_type=MessageType.TOOL_CALL,
                        tool_call_id=tool_call.tool_call_id,
                        image_files=None,
                    )
                    simple_chat_history.append(tool_call_msg)

                    tool_response_message = tool_response.llm_facing_response
                    tool_response_token_count = len(
                        tokenizer_func(tool_response_message)
                    )

                    tool_response_msg = ChatMessageSimple(
                        message=tool_response_message,
                        token_count=tool_response_token_count,
                        message_type=MessageType.TOOL_CALL_RESPONSE,
                        tool_call_id=tool_call.tool_call_id,
                        image_files=None,
                    )
                    simple_chat_history.append(tool_response_msg)

                    # Update citation processor if this was a search tool
                    if tool_call.tool_name in citeable_tools_names:
                        # Check if the rich_response is a SearchDocsResponse
                        if isinstance(tool_response.rich_response, SearchDocsResponse):
                            search_response = tool_response.rich_response

                            # Create mapping from citation number to SearchDoc
                            citation_to_doc: dict[int, SearchDoc] = {}
                            for (
                                citation_num,
                                doc_id,
                            ) in search_response.citation_mapping.items():
                                # Find the SearchDoc with this doc_id
                                matching_doc = next(
                                    (
                                        doc
                                        for doc in search_response.search_docs
                                        if doc.document_id == doc_id
                                    ),
                                    None,
                                )
                                if matching_doc:
                                    citation_to_doc[citation_num] = matching_doc

                            # Update the citation processor
                            citation_processor.update_citation_mapping(citation_to_doc)

                current_tool_call_index += 1

            # If no tool calls, then it must have answered, wrap up
            if not llm_step_result.tool_calls or len(llm_step_result.tool_calls) == 0:
                break

            # Certain tools do not allow further actions, force the LLM wrap up on the next cycle
            if any(
                tool.tool_name in stopping_tools_names
                for tool in llm_step_result.tool_calls
            ):
                ran_image_gen = True

            if llm_step_result.tool_calls and any(
                tool.tool_name in citeable_tools_names
                for tool in llm_step_result.tool_calls
            ):
                # As long as 1 tool with citeable documents is called at any point, we ask the LLM to try to cite
                should_cite_documents = True

        if not llm_step_result or not llm_step_result.answer:
            raise RuntimeError("LLM did not return an answer.")

        # Note: All state (answer, reasoning, citations, tool_calls) is saved incrementally
        # in state_container. The process_message layer will persist to DB.

        # Signal completion
        emitter.emit(
            Packet(turn_index=current_tool_call_index, obj=OverallStop(type="stop"))
        )
