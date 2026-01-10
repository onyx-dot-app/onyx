from collections.abc import Callable

from sqlalchemy.orm import Session

from onyx.chat.chat_state import ChatStateContainer
from onyx.chat.chat_utils import create_tool_call_failure_messages
from onyx.chat.citation_processor import CitationMapping
from onyx.chat.citation_processor import DynamicCitationProcessor
from onyx.chat.citation_utils import update_citation_processor_from_tool_response
from onyx.chat.emitter import Emitter
from onyx.chat.llm_step import run_llm_step
from onyx.chat.models import ChatMessageSimple
from onyx.chat.models import ExtractedProjectFiles
from onyx.chat.models import LlmStepResult
from onyx.chat.models import ProjectFileMetadata
from onyx.chat.prompt_utils import build_reminder_message
from onyx.chat.prompt_utils import build_system_prompt
from onyx.chat.prompt_utils import (
    get_default_base_system_prompt,
)
from onyx.configs.constants import DocumentSource
from onyx.configs.constants import MessageType
from onyx.context.search.models import SearchDoc
from onyx.context.search.models import SearchDocsResponse
from onyx.db.models import Persona
from onyx.llm.interfaces import LLM
from onyx.llm.interfaces import LLMUserIdentity
from onyx.llm.interfaces import ToolChoiceOptions
from onyx.llm.utils import model_needs_formatting_reenabled
from onyx.prompts.chat_prompts import IMAGE_GEN_REMINDER
from onyx.prompts.chat_prompts import OPEN_URL_REMINDER
from onyx.server.query_and_chat.placement import Placement
from onyx.server.query_and_chat.streaming_models import OverallStop
from onyx.server.query_and_chat.streaming_models import Packet
from onyx.server.query_and_chat.streaming_models import TopLevelBranching
from onyx.tools.built_in_tools import CITEABLE_TOOLS_NAMES
from onyx.tools.built_in_tools import STOPPING_TOOLS_NAMES
from onyx.tools.interface import Tool
from onyx.tools.models import ToolCallInfo
from onyx.tools.models import ToolResponse
from onyx.tools.tool_implementations.images.models import (
    FinalImageGenerationResponse,
)
from onyx.tools.tool_implementations.search.search_tool import SearchTool
from onyx.tools.tool_implementations.web_search.web_search_tool import WebSearchTool
from onyx.tools.tool_runner import run_tool_calls
from onyx.tracing.framework.create import trace
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


def construct_message_history(
    system_prompt: ChatMessageSimple | None,
    custom_agent_prompt: ChatMessageSimple | None,
    simple_chat_history: list[ChatMessageSimple],
    reminder_message: ChatMessageSimple | None,
    project_files: ExtractedProjectFiles | None,
    available_tokens: int,
    last_n_user_messages: int | None = None,
) -> list[ChatMessageSimple]:
    if last_n_user_messages is not None:
        if last_n_user_messages <= 0:
            raise ValueError(
                "filtering chat history by last N user messages must be a value greater than 0"
            )

    history_token_budget = available_tokens
    history_token_budget -= system_prompt.token_count if system_prompt else 0
    history_token_budget -= (
        custom_agent_prompt.token_count if custom_agent_prompt else 0
    )
    if project_files:
        history_token_budget -= project_files.total_token_count
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
        if project_files and project_files.project_file_texts:
            project_message = _create_project_files_message(
                project_files, token_counter=None
            )
            result.append(project_message)
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

    # Truncate history_before_last_user from the top to fit in remaining budget
    truncated_history_before: list[ChatMessageSimple] = []
    current_token_count = 0

    for msg in reversed(history_before_last_user):
        if current_token_count + msg.token_count <= remaining_budget:
            msg.should_cache = True
            truncated_history_before.insert(0, msg)
            current_token_count += msg.token_count
        else:
            # Can't fit this message, stop truncating
            break

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
    # [last_user_message], [messages_after_last_user], [reminder]
    result = [system_prompt] if system_prompt else []

    # 1. Add truncated history before last user message
    result.extend(truncated_history_before)

    # 2. Add custom agent prompt (inserted before last user message)
    if custom_agent_prompt:
        result.append(custom_agent_prompt)

    # 3. Add project files message (inserted before last user message)
    if project_files and project_files.project_file_texts:
        project_message = _create_project_files_message(
            project_files, token_counter=None
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
    token_counter: Callable[[str], int] | None,
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
    memories: list[str] | None,
    llm: LLM,
    token_counter: Callable[[str], int],
    db_session: Session,
    forced_tool_id: int | None = None,
    user_identity: LLMUserIdentity | None = None,
    chat_session_id: str | None = None,
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

        # Initialize citation processor for handling citations dynamically
        citation_processor = DynamicCitationProcessor()

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
        citation_mapping: dict[int, str] = {}  # Maps citation_num -> document_id/URL

        default_base_system_prompt: str = get_default_base_system_prompt(db_session)
        system_prompt = None
        custom_agent_prompt_msg = None

        reasoning_cycles = 0
        for llm_cycle_count in range(MAX_LLM_CYCLES):
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

            # The section below calculates the available tokens for history a bit more accurately
            # now that project files are loaded in.
            if persona and persona.replace_base_system_prompt and persona.system_prompt:
                # Handles the case where user has checked off the "Replace base system prompt" checkbox
                system_prompt = ChatMessageSimple(
                    message=persona.system_prompt,
                    token_count=token_counter(persona.system_prompt),
                    message_type=MessageType.SYSTEM,
                )
                custom_agent_prompt_msg = None
            else:
                # If it's an empty string, we assume the user does not want to include it as an empty System message
                if default_base_system_prompt:
                    open_ai_formatting_enabled = model_needs_formatting_reenabled(
                        llm.config.model_name
                    )

                    system_prompt_str = build_system_prompt(
                        base_system_prompt=default_base_system_prompt,
                        datetime_aware=persona.datetime_aware if persona else True,
                        memories=memories,
                        tools=tools,
                        should_cite_documents=should_cite_documents
                        or always_cite_documents,
                        open_ai_formatting_enabled=open_ai_formatting_enabled,
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
                    is_last_cycle=out_of_cycles,
                )

            reminder_msg = (
                ChatMessageSimple(
                    message=reminder_message_text,
                    token_count=token_counter(reminder_message_text),
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

            # This calls the LLM, yields packets (reasoning, answers, etc.) and returns the result
            # It also pre-processes the tool calls in preparation for running them
            llm_step_result, has_reasoned = run_llm_step(
                emitter=emitter,
                history=truncated_message_history,
                tool_definitions=[tool.tool_definition() for tool in final_tools],
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
            )
            if has_reasoned:
                reasoning_cycles += 1

            # Save citation mapping after each LLM step for incremental state updates
            state_container.set_citation_mapping(citation_processor.citation_to_doc)

            # Run the LLM selected tools, there is some more logic here than a simple execution
            # each tool might have custom logic here
            tool_responses: list[ToolResponse] = []
            tool_calls = llm_step_result.tool_calls or []

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
                memories=memories,
                user_info=None,  # TODO, this is part of memories right now, might want to separate it out
                citation_mapping=citation_mapping,
                next_citation_num=citation_processor.get_next_citation_number(),
                max_concurrent_tools=None,
                skip_search_query_expansion=has_called_search_tool,
            )
            tool_responses = parallel_tool_call_results.tool_responses
            citation_mapping = parallel_tool_call_results.updated_citation_mapping

            # Failure case, give something reasonable to the LLM to try again
            if tool_calls and not tool_responses:
                failure_messages = create_tool_call_failure_messages(
                    tool_calls[0], token_counter
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
                    turn_index=llm_cycle_count + reasoning_cycles,
                    tab_index=tab_index,
                    tool_name=tool_call.tool_name,
                    tool_call_id=tool_call.tool_call_id,
                    tool_id=tool.id,
                    reasoning_tokens=llm_step_result.reasoning,  # All tool calls from this loop share the same reasoning
                    tool_call_arguments=tool_call.tool_args,
                    tool_call_response=tool_response.llm_facing_response,
                    search_docs=search_docs,
                    generated_images=generated_images,
                )
                # Add to state container for partial save support
                state_container.add_tool_call(tool_call_info)

                # Store tool call with function name and arguments in separate layers
                tool_call_message = tool_call.to_msg_str()
                tool_call_token_count = token_counter(tool_call_message)

                tool_call_msg = ChatMessageSimple(
                    message=tool_call_message,
                    token_count=tool_call_token_count,
                    message_type=MessageType.TOOL_CALL,
                    tool_call_id=tool_call.tool_call_id,
                    image_files=None,
                )
                simple_chat_history.append(tool_call_msg)

                tool_response_message = tool_response.llm_facing_response
                tool_response_token_count = token_counter(tool_response_message)

                tool_response_msg = ChatMessageSimple(
                    message=tool_response_message,
                    token_count=tool_response_token_count,
                    message_type=MessageType.TOOL_CALL_RESPONSE,
                    tool_call_id=tool_call.tool_call_id,
                    image_files=None,
                )
                simple_chat_history.append(tool_response_msg)

                # Update citation processor if this was a search tool
                update_citation_processor_from_tool_response(
                    tool_response, citation_processor
                )

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
            raise RuntimeError("LLM did not return an answer.")

        emitter.emit(
            Packet(
                placement=Placement(turn_index=llm_cycle_count + reasoning_cycles),
                obj=OverallStop(type="stop"),
            )
        )
