from collections.abc import Mapping

from pydantic import BaseModel, Field, JsonValue, TypeAdapter, ValidationError
from sqlalchemy.orm import Session

from onyx.agents.transcript import AgentTranscript, RunStatus
from onyx.chat.citation_utils import extract_citation_order_from_text
from onyx.chat.models import ChatExecutionRecord, MessagePresentation, PresentationMode
from onyx.chat.renderer import (
    PacketRenderer,
    RenderConfig,
    render_config,
    render_message,
)
from onyx.chat.tool_progress import project_tool_progress, tool_display_progress
from onyx.coding_agent.tool_definitions import (
    CODING_AGENT_QUERY_KEY,
    CODING_AGENT_REPO_KEY,
)
from onyx.configs.constants import MessageType
from onyx.context.search.models import SavedSearchDoc, SearchDoc
from onyx.db.agent_transcript import read_chat_execution
from onyx.db.chat import (
    get_db_search_doc_by_id,
    translate_db_search_doc_to_saved_search_doc,
)
from onyx.db.models import ChatMessage, Tool, ToolCall
from onyx.db.tools import (
    get_response_tool_records,
    get_tool_by_id,
    get_tools_by_ids,
    restore_tool_result,
)
from onyx.deep_research.tool_definitions import (
    RESEARCH_AGENT_IN_CODE_ID,
    RESEARCH_AGENT_TASK_KEY,
)
from onyx.llm.models import AssistantMessage, ToolResultMessage
from onyx.server.query_and_chat.placement import Placement
from onyx.server.query_and_chat.streaming_models import (
    AgentResponseDelta,
    AgentResponseStart,
    CitationInfo,
    CodingAgentFinal,
    CodingAgentStart,
    CustomToolArgs,
    CustomToolDelta,
    CustomToolStart,
    FileReaderResult,
    FileReaderStart,
    ImageGenerationFinal,
    ImageGenerationToolStart,
    IntermediateReportDelta,
    IntermediateReportStart,
    MemoryToolDelta,
    MemoryToolStart,
    OpenUrlDocuments,
    OpenUrlStart,
    OpenUrlUrls,
    OperationStatus,
    OverallStop,
    Packet,
    PacketIdentity,
    PythonToolDelta,
    PythonToolStart,
    ReasoningDelta,
    ReasoningStart,
    ResearchAgentStart,
    SearchToolDocumentsDelta,
    SearchToolQueriesDelta,
    SearchToolStart,
    SectionEnd,
    TopLevelBranching,
)
from onyx.tools.models import CustomToolCallSummary
from onyx.tools.progress import (
    CustomToolErrorInfo,
    GeneratedImage,
    MemoryOperation,
    MemoryUpdated,
)
from onyx.tools.tool_implementations.coding_agent.coding_agent_tool import (
    CodingAgentArguments,
    CodingAgentTool,
)
from onyx.tools.tool_implementations.file_reader.file_reader_tool import FileReaderTool
from onyx.tools.tool_implementations.images.image_generation_tool import (
    ImageGenerationTool,
)
from onyx.tools.tool_implementations.memory.memory_tool import MemoryTool
from onyx.tools.tool_implementations.open_url.open_url_tool import OpenURLTool
from onyx.tools.tool_implementations.python.python_tool import (
    PythonArguments,
    PythonTool,
)
from onyx.tools.tool_implementations.search.search_tool import (
    SearchArguments,
    SearchTool,
)
from onyx.tools.tool_implementations.web_search.web_search_tool import WebSearchTool
from onyx.utils.logger import setup_logger

logger = setup_logger()

_STRING_LIST = TypeAdapter(list[str])
_TEXT = TypeAdapter(str)
_JSON_OBJECT = TypeAdapter(dict[str, JsonValue])
_FILE_IDS = TypeAdapter(list[str] | None)


class _SavedPythonFile(BaseModel):
    file_link: str = ""


class _SavedPythonResult(BaseModel):
    """Read Python results whose older records can omit execution metadata."""

    stdout: str = ""
    stderr: str = ""
    generated_files: list[_SavedPythonFile] = Field(default_factory=list)


class _SavedCustomToolSummary(CustomToolCallSummary):
    tool_result: JsonValue = None
    response_type: str = "text"


def create_message_packets(
    message_text: str,
    final_documents: list[SearchDoc] | None,
    turn_index: int,
) -> list[Packet]:
    packets: list[Packet] = []

    final_search_docs: list[SearchDoc] | None = None
    if final_documents:
        sorted_final_documents = sorted(
            final_documents, key=lambda x: x.score or 0.0, reverse=True
        )
        final_search_docs = [
            SearchDoc(**doc.model_dump()) for doc in sorted_final_documents
        ]

    packets.append(
        Packet(
            placement=Placement(turn_index=turn_index),
            obj=AgentResponseStart(
                final_documents=final_search_docs,
            ),
        )
    )

    packets.append(
        Packet(
            placement=Placement(turn_index=turn_index),
            obj=AgentResponseDelta(
                content=message_text,
            ),
        ),
    )

    packets.append(
        Packet(
            placement=Placement(turn_index=turn_index),
            obj=SectionEnd(),
        )
    )

    return packets


def create_citation_packets(
    citation_info_list: list[CitationInfo], turn_index: int
) -> list[Packet]:
    packets: list[Packet] = [
        Packet(
            placement=Placement(turn_index=turn_index),
            obj=citation_info,
        )
        for citation_info in citation_info_list
    ]

    packets.append(Packet(placement=Placement(turn_index=turn_index), obj=SectionEnd()))

    return packets


def create_reasoning_packets(reasoning_text: str, turn_index: int) -> list[Packet]:
    packets: list[Packet] = []

    packets.append(
        Packet(placement=Placement(turn_index=turn_index), obj=ReasoningStart())
    )

    packets.append(
        Packet(
            placement=Placement(turn_index=turn_index),
            obj=ReasoningDelta(
                reasoning=reasoning_text,
            ),
        ),
    )

    packets.append(Packet(placement=Placement(turn_index=turn_index), obj=SectionEnd()))

    return packets


def create_image_generation_packets(
    images: list[GeneratedImage], turn_index: int, tab_index: int = 0
) -> list[Packet]:
    packets: list[Packet] = []

    packets.append(
        Packet(
            placement=Placement(turn_index=turn_index, tab_index=tab_index),
            obj=ImageGenerationToolStart(),
        )
    )

    packets.append(
        Packet(
            placement=Placement(turn_index=turn_index, tab_index=tab_index),
            obj=ImageGenerationFinal(images=images),
        ),
    )

    packets.append(
        Packet(
            placement=Placement(turn_index=turn_index, tab_index=tab_index),
            obj=SectionEnd(),
        )
    )

    return packets


def create_custom_tool_packets(
    tool_name: str,
    response_type: str,
    turn_index: int,
    tab_index: int = 0,
    data: JsonValue = None,
    file_ids: list[str] | None = None,
    error: CustomToolErrorInfo | None = None,
    tool_args: dict[str, JsonValue] | None = None,
    tool_id: int | None = None,
) -> list[Packet]:
    packets: list[Packet] = []

    packets.append(
        Packet(
            placement=Placement(turn_index=turn_index, tab_index=tab_index),
            obj=CustomToolStart(tool_name=tool_name, tool_id=tool_id),
        )
    )

    if tool_args:
        packets.append(
            Packet(
                placement=Placement(turn_index=turn_index, tab_index=tab_index),
                obj=CustomToolArgs(tool_name=tool_name, tool_args=tool_args),
            )
        )

    packets.append(
        Packet(
            placement=Placement(turn_index=turn_index, tab_index=tab_index),
            obj=CustomToolDelta(
                tool_name=tool_name,
                tool_id=tool_id,
                response_type=response_type,
                data=data,
                file_ids=file_ids,
                error=error,
            ),
        ),
    )

    packets.append(
        Packet(
            placement=Placement(turn_index=turn_index, tab_index=tab_index),
            obj=SectionEnd(),
        )
    )

    return packets


def create_file_reader_packets(
    summary_json: str,
    turn_index: int,
    tab_index: int = 0,
) -> list[Packet]:
    """Restore the saved file range and previews."""
    placement = Placement(turn_index=turn_index, tab_index=tab_index)
    packets = [Packet(placement=placement, obj=FileReaderStart())]
    try:
        result = FileReaderResult.model_validate_json(summary_json)
    except ValidationError:
        logger.debug(
            "Saved file-reader response has no structured summary", exc_info=True
        )
    else:
        packets.append(Packet(placement=placement, obj=result))

    packets.append(Packet(placement=placement, obj=SectionEnd()))
    return packets


def create_research_agent_packets(
    research_task: str,
    report_content: str | None,
    turn_index: int,
    tab_index: int = 0,
) -> list[Packet]:
    """Restore the research task and accepted report."""
    packets: list[Packet] = []

    packets.append(
        Packet(
            placement=Placement(turn_index=turn_index, tab_index=tab_index),
            obj=ResearchAgentStart(research_task=research_task),
        )
    )

    if report_content:
        packets.append(
            Packet(
                placement=Placement(turn_index=turn_index, tab_index=tab_index),
                obj=IntermediateReportStart(),
            )
        )

        packets.append(
            Packet(
                placement=Placement(turn_index=turn_index, tab_index=tab_index),
                obj=IntermediateReportDelta(content=report_content),
            )
        )

    packets.append(
        Packet(
            placement=Placement(turn_index=turn_index, tab_index=tab_index),
            obj=SectionEnd(),
        )
    )

    return packets


def create_coding_agent_packets(
    query: str,
    repo: str,
    answer: str | None,
    turn_index: int,
    tab_index: int = 0,
) -> list[Packet]:
    """Restore the coding task input and accepted answer."""
    placement = Placement(turn_index=turn_index, tab_index=tab_index)
    packets: list[Packet] = [
        Packet(placement=placement, obj=CodingAgentStart(query=query, repo=repo)),
    ]

    if answer:
        packets.append(
            Packet(placement=placement, obj=CodingAgentFinal(answer=answer)),
        )

    packets.append(Packet(placement=placement, obj=SectionEnd()))

    return packets


def create_fetch_packets(
    fetch_docs: list[SavedSearchDoc],
    urls: list[str],
    turn_index: int,
    tab_index: int = 0,
) -> list[Packet]:
    packets: list[Packet] = []
    packets.append(
        Packet(
            placement=Placement(turn_index=turn_index, tab_index=tab_index),
            obj=OpenUrlStart(),
        )
    )
    packets.append(
        Packet(
            placement=Placement(turn_index=turn_index, tab_index=tab_index),
            obj=OpenUrlUrls(urls=urls),
        )
    )
    packets.append(
        Packet(
            placement=Placement(turn_index=turn_index, tab_index=tab_index),
            obj=OpenUrlDocuments(
                documents=[SearchDoc(**doc.model_dump()) for doc in fetch_docs]
            ),
        )
    )
    packets.append(
        Packet(
            placement=Placement(turn_index=turn_index, tab_index=tab_index),
            obj=SectionEnd(),
        )
    )
    return packets


def create_memory_packets(
    memory_text: str,
    operation: MemoryOperation,
    memory_id: int | None,
    turn_index: int,
    tab_index: int = 0,
    index: int | None = None,
) -> list[Packet]:
    packets: list[Packet] = []

    packets.append(
        Packet(
            placement=Placement(turn_index=turn_index, tab_index=tab_index),
            obj=MemoryToolStart(),
        )
    )

    packets.append(
        Packet(
            placement=Placement(turn_index=turn_index, tab_index=tab_index),
            obj=MemoryToolDelta(
                memory_text=memory_text,
                operation=operation,
                memory_id=memory_id,
                index=index,
            ),
        ),
    )

    packets.append(
        Packet(
            placement=Placement(turn_index=turn_index, tab_index=tab_index),
            obj=SectionEnd(),
        )
    )

    return packets


def create_python_tool_packets(
    code: str,
    stdout: str,
    stderr: str,
    file_ids: list[str],
    turn_index: int,
    tab_index: int = 0,
) -> list[Packet]:
    """Restore Python input, output, and generated file references."""
    packets: list[Packet] = []
    placement = Placement(turn_index=turn_index, tab_index=tab_index)

    packets.append(Packet(placement=placement, obj=PythonToolStart(code=code)))

    packets.append(
        Packet(
            placement=placement,
            obj=PythonToolDelta(
                stdout=stdout,
                stderr=stderr,
                file_ids=file_ids,
            ),
        )
    )

    packets.append(Packet(placement=placement, obj=SectionEnd()))
    return packets


def create_search_packets(
    search_queries: list[str],
    search_docs: list[SavedSearchDoc],
    is_internet_search: bool,
    turn_index: int,
    tab_index: int = 0,
) -> list[Packet]:
    packets: list[Packet] = []

    packets.append(
        Packet(
            placement=Placement(turn_index=turn_index, tab_index=tab_index),
            obj=SearchToolStart(
                is_internet_search=is_internet_search,
            ),
        )
    )

    if search_queries:
        packets.append(
            Packet(
                placement=Placement(turn_index=turn_index, tab_index=tab_index),
                obj=SearchToolQueriesDelta(queries=search_queries),
            ),
        )

    if search_docs:
        sorted_search_docs = sorted(
            search_docs, key=lambda x: x.score or 0.0, reverse=True
        )
        packets.append(
            Packet(
                placement=Placement(turn_index=turn_index, tab_index=tab_index),
                obj=SearchToolDocumentsDelta(
                    documents=[
                        SearchDoc(**doc.model_dump()) for doc in sorted_search_docs
                    ]
                ),
            ),
        )

    packets.append(
        Packet(
            placement=Placement(turn_index=turn_index, tab_index=tab_index),
            obj=SectionEnd(),
        )
    )

    return packets


def _saved_tool_packets(tool_call: ToolCall, tool: Tool) -> list[Packet]:
    """Reconstruct display content from a saved tool's domain result."""
    turn_num = tool_call.turn_number
    packets: list[Packet] = []
    if tool.in_code_tool_id in [
        SearchTool.__name__,
        WebSearchTool.__name__,
    ]:
        queries = SearchArguments.model_validate(
            {"queries": tool_call.tool_call_arguments.get("queries", [])}
        ).queries
        search_docs: list[SavedSearchDoc] = [
            translate_db_search_doc_to_saved_search_doc(doc)
            for doc in tool_call.search_docs
        ]
        packets.extend(
            create_search_packets(
                search_queries=queries,
                search_docs=search_docs,
                is_internet_search=tool.in_code_tool_id == WebSearchTool.__name__,
                turn_index=turn_num,
                tab_index=tool_call.tab_index,
            )
        )

    elif tool.in_code_tool_id == OpenURLTool.__name__:
        fetch_docs: list[SavedSearchDoc] = [
            translate_db_search_doc_to_saved_search_doc(doc)
            for doc in tool_call.search_docs
        ]
        urls = _STRING_LIST.validate_python(
            tool_call.tool_call_arguments.get("urls", [])
        )
        packets.extend(
            create_fetch_packets(
                fetch_docs,
                urls,
                turn_num,
                tab_index=tool_call.tab_index,
            )
        )

    elif tool.in_code_tool_id == ImageGenerationTool.__name__:
        if tool_call.generated_images:
            images = [
                GeneratedImage.model_validate(img) for img in tool_call.generated_images
            ]
            packets.extend(
                create_image_generation_packets(
                    images, turn_num, tab_index=tool_call.tab_index
                )
            )

    elif tool.in_code_tool_id == FileReaderTool.__name__:
        packets.extend(
            create_file_reader_packets(
                summary_json=tool_call.tool_call_response or "",
                turn_index=turn_num,
                tab_index=tool_call.tab_index,
            )
        )

    elif tool.in_code_tool_id == RESEARCH_AGENT_IN_CODE_ID:
        research_task = _TEXT.validate_python(
            tool_call.tool_call_arguments.get(RESEARCH_AGENT_TASK_KEY)
            or "Could not fetch saved research task."
        )
        packets.extend(
            create_research_agent_packets(
                research_task=research_task,
                report_content=tool_call.tool_call_response,
                turn_index=turn_num,
                tab_index=tool_call.tab_index,
            )
        )

    elif tool.in_code_tool_id == CodingAgentTool.__name__:
        arguments = CodingAgentArguments.model_validate(
            {
                CODING_AGENT_QUERY_KEY: tool_call.tool_call_arguments.get(
                    CODING_AGENT_QUERY_KEY
                )
                or "",
                CODING_AGENT_REPO_KEY: tool_call.tool_call_arguments.get(
                    CODING_AGENT_REPO_KEY
                )
                or "",
            }
        )
        packets.extend(
            create_coding_agent_packets(
                query=arguments.query,
                repo=arguments.github_repo,
                answer=tool_call.tool_call_response,
                turn_index=turn_num,
                tab_index=tool_call.tab_index,
            )
        )

    elif tool.in_code_tool_id == MemoryTool.__name__:
        if tool_call.tool_call_response:
            memory_data = MemoryUpdated.model_validate_json(
                tool_call.tool_call_response
            )
            packets.extend(
                create_memory_packets(
                    memory_text=memory_data.memory_text,
                    operation=memory_data.operation,
                    memory_id=memory_data.memory_id,
                    turn_index=turn_num,
                    tab_index=tool_call.tab_index,
                    index=memory_data.index,
                )
            )

    elif tool.in_code_tool_id == PythonTool.__name__:
        code = PythonArguments.model_validate(
            {"code": tool_call.tool_call_arguments.get("code", "")}
        ).code
        stdout = ""
        stderr = ""
        file_ids: list[str] = []
        if tool_call.tool_call_response:
            try:
                response_data = _SavedPythonResult.model_validate_json(
                    tool_call.tool_call_response
                )
            except ValidationError:
                logger.debug("Saved Python response uses plain text", exc_info=True)
                stdout = tool_call.tool_call_response
            else:
                stdout = response_data.stdout
                stderr = response_data.stderr
                file_ids = [
                    file.file_link.rsplit("/", 1)[-1]
                    for file in response_data.generated_files
                    if file.file_link
                ]
        packets.extend(
            create_python_tool_packets(
                code=code,
                stdout=stdout,
                stderr=stderr,
                file_ids=file_ids,
                turn_index=turn_num,
                tab_index=tool_call.tab_index,
            )
        )

    else:
        custom_data: JsonValue = tool_call.tool_call_response
        custom_error: CustomToolErrorInfo | None = None
        custom_response_type = "text"
        try:
            summary = _SavedCustomToolSummary.model_validate_json(
                tool_call.tool_call_response
            )
        except ValidationError:
            logger.debug("Saved custom tool response uses plain text", exc_info=True)
        else:
            custom_data = summary.tool_result
            custom_response_type = summary.response_type
            custom_error = summary.error

        custom_file_ids: list[str] | None = None
        if custom_response_type in ("image", "csv") and isinstance(custom_data, dict):
            custom_file_ids = _FILE_IDS.validate_python(custom_data.get("file_ids"))
            custom_data = None

        custom_args = {
            k: v
            for k, v in _JSON_OBJECT.validate_python(
                tool_call.tool_call_arguments or {}
            ).items()
            if k != "requestBody"
        }
        packets.extend(
            create_custom_tool_packets(
                tool_name=tool.display_name or tool.name,
                response_type=custom_response_type,
                turn_index=turn_num,
                tab_index=tool_call.tab_index,
                data=custom_data,
                file_ids=custom_file_ids,
                error=custom_error,
                tool_args=custom_args if custom_args else None,
                tool_id=tool_call.tool_id,
            )
        )

    return packets


def translate_assistant_message_to_packets(
    chat_message: ChatMessage,
    db_session: Session,
) -> list[Packet]:
    """
    Translates an assistant message and tool calls to packet format.
    It needs to be a list of list of packets combined into indices for "steps".
    The final answer and citations are also a "step".
    """
    execution = read_chat_execution(chat_message)
    if execution is not None and execution.transcript.run_id is not None:
        return _execution_packets(chat_message, execution, db_session)
    packet_list: list[Packet] = []

    if chat_message.message_type != MessageType.ASSISTANT:
        raise ValueError(f"Chat message {chat_message.id} is not an assistant message")

    if chat_message.tool_calls:
        # Group tool calls by turn_number
        tool_calls_by_turn: dict[int, list] = {}
        for tool_call in chat_message.tool_calls:
            turn_num = tool_call.turn_number
            if turn_num not in tool_calls_by_turn:
                tool_calls_by_turn[turn_num] = []
            tool_calls_by_turn[turn_num].append(tool_call)

        tool_call_turns = set(tool_calls_by_turn.keys())
        # Process each turn in order
        for turn_num in sorted(tool_calls_by_turn.keys()):
            tool_calls_in_turn = tool_calls_by_turn[turn_num]

            # Insert pre-tool reasoning once per turn (if available)
            turn_reasoning = next(
                (
                    tool_call.reasoning_tokens
                    for tool_call in tool_calls_in_turn
                    if tool_call.reasoning_tokens
                ),
                None,
            )
            if turn_reasoning:
                # Use the previous turn slot when free to preserve reasoning-before-tool ordering.
                reasoning_turn_index = turn_num
                if turn_num > 0 and (turn_num - 1) not in tool_call_turns:
                    reasoning_turn_index = turn_num - 1
                packet_list.extend(
                    create_reasoning_packets(
                        reasoning_text=turn_reasoning,
                        turn_index=reasoning_turn_index,
                    )
                )

            # Process each tool call in this turn (single pass).
            # We buffer packets for the turn so we can conditionally prepend a TopLevelBranching
            # packet (which must appear before any tool output in the turn).
            research_agent_count = 0
            turn_tool_packets: list[Packet] = []
            for tool_call in tool_calls_in_turn:
                # Here we do a try because some tools may get deleted before the session is reloaded.
                try:
                    tool = get_tool_by_id(tool_call.tool_id, db_session)
                    if tool.in_code_tool_id == RESEARCH_AGENT_IN_CODE_ID:
                        research_agent_count += 1

                    turn_tool_packets.extend(_saved_tool_packets(tool_call, tool))

                except Exception as e:
                    logger.warning("Error processing tool call %s: %s", tool_call.id, e)
                    continue

            if research_agent_count > 1:
                packet_list.append(
                    Packet(
                        placement=Placement(turn_index=turn_num),
                        obj=TopLevelBranching(
                            num_parallel_branches=research_agent_count
                        ),
                    )
                )
            packet_list.extend(turn_tool_packets)

    # Determine the next turn_index for the final message
    # It should come after all tool calls
    max_tool_turn = 0
    if chat_message.tool_calls:
        max_tool_turn = max(tc.turn_number for tc in chat_message.tool_calls)

    citations = chat_message.citations
    citation_info_list: list[CitationInfo] = []

    if citations:
        for citation_num, search_doc_id in citations.items():
            search_doc = get_db_search_doc_by_id(search_doc_id, db_session)
            if search_doc:
                citation_info_list.append(
                    CitationInfo(
                        citation_number=citation_num,
                        document_id=search_doc.document_id,
                    )
                )

        # Sort citations by order of appearance in message text
        citation_order = extract_citation_order_from_text(chat_message.message or "")
        order_map = {num: idx for idx, num in enumerate(citation_order)}
        citation_info_list.sort(
            key=lambda c: order_map.get(c.citation_number, float("inf"))
        )

    # Message comes after tool calls, with optional reasoning step beforehand
    message_turn_index = max_tool_turn + 1
    if chat_message.reasoning_tokens:
        packet_list.extend(
            create_reasoning_packets(
                reasoning_text=chat_message.reasoning_tokens,
                turn_index=message_turn_index,
            )
        )
        message_turn_index += 1

    if chat_message.message:
        packet_list.extend(
            create_message_packets(
                message_text=chat_message.message,
                final_documents=[
                    translate_db_search_doc_to_saved_search_doc(doc)
                    for doc in chat_message.search_docs
                ],
                turn_index=message_turn_index,
            )
        )

    # Citations come after the message
    citation_turn_index = (
        message_turn_index + 1 if citation_info_list else message_turn_index
    )

    if len(citation_info_list) > 0:
        packet_list.extend(
            create_citation_packets(citation_info_list, citation_turn_index)
        )

    # Return the highest turn_index used
    final_turn_index = 0
    if chat_message.message_type == MessageType.ASSISTANT:
        max_tool_turn = 0
        if chat_message.tool_calls:
            max_tool_turn = max(tc.turn_number for tc in chat_message.tool_calls)

        final_turn_index = max_tool_turn
        if chat_message.reasoning_tokens:
            final_turn_index = max(final_turn_index, max_tool_turn + 1)
        if chat_message.message:
            final_turn_index = max(final_turn_index, message_turn_index)
        if citation_info_list:
            final_turn_index = max(final_turn_index, citation_turn_index)

    # Determine stop reason - check if message indicates user cancelled
    stop_reason: str | None = None
    if chat_message.message:
        if "generation was stopped" in chat_message.message.lower():
            stop_reason = "user_cancelled"

    # Add overall stop packet at the end
    packet_list.append(
        Packet(
            placement=Placement(turn_index=final_turn_index),
            obj=OverallStop(stop_reason=stop_reason),
        )
    )

    return packet_list


def _execution_packets(
    chat_message: ChatMessage, execution: ChatExecutionRecord, db_session: Session
) -> list[Packet]:
    records = {
        record.id: record
        for record in get_response_tool_records(
            [reference.record_id for reference in execution.tool_records],
            chat_message.chat_session_id,
            db_session,
        )
    }
    tools = {
        tool.id: tool
        for tool in get_tools_by_ids(
            list({record.tool_id for record in records.values()}), db_session
        )
    }
    references = {
        (reference.message_id, reference.tool_call_id): records[reference.record_id]
        for reference in execution.tool_records
    }
    settings = {
        (setting.run_id, setting.step_index): setting
        for setting in execution.presentation
    }
    documents = {
        doc.document_id: translate_db_search_doc_to_saved_search_doc(doc)
        for doc in chat_message.search_docs
    }
    for record in records.values():
        documents.update(
            {
                doc.document_id: translate_db_search_doc_to_saved_search_doc(doc)
                for doc in record.search_docs
            }
        )
    return _execution_run_packets(
        execution.transcript, chat_message.id, references, tools, settings, documents
    )


def _execution_run_packets(
    transcript: AgentTranscript,
    response_id: int,
    records: dict[tuple[str, str], ToolCall],
    tools: dict[int, Tool],
    settings: dict[tuple[str, int], MessagePresentation],
    documents: Mapping[str, SearchDoc],
    default_mode: PresentationMode = PresentationMode.ANSWER,
) -> list[Packet]:
    if transcript.run_id is None:
        raise ValueError("Execution record has no run identity")
    base = PacketIdentity(
        response_id=response_id,
        run_id=transcript.run_id,
        agent_id=transcript.agent_id,
        agent_path=transcript.agent_path,
        message_id=f"{transcript.run_id}:0",
        parent_run_id=transcript.parent_run_id,
        parent_message_id=transcript.parent_message_id,
        parent_tool_call_id=transcript.parent_tool_call_id,
    )
    packets = [
        Packet(
            identity=base.model_copy(update={"part_id": "run"}),
            obj=OperationStatus(status=RunStatus.RUNNING),
        )
    ]
    for operation in transcript.operations:
        if operation.tool_call_id is not None:
            continue
        message = transcript.messages[operation.message_index]
        if not isinstance(message, AssistantMessage):
            raise ValueError("Recorded message operation has invalid output")
        identity = base.model_copy(
            update={"message_id": f"{transcript.run_id}:{operation.step_index}"}
        )
        setting = settings.get((transcript.run_id, operation.step_index))
        config = RenderConfig(mode=default_mode)
        if setting is not None:
            config = render_config(setting, documents)
        renderer = PacketRenderer(config, identity)
        packets.extend(
            render_message(
                renderer, message, complete=operation.status == RunStatus.COMPLETE
            )
        )
        results: dict[str, ToolResultMessage] = {}
        for following in transcript.messages[operation.message_index + 1 :]:
            if isinstance(following, AssistantMessage):
                break
            if isinstance(following, ToolResultMessage):
                results[following.tool_call_id] = following
        for call in message.tool_calls:
            call_identity = identity.model_copy(
                update={"tool_call_id": call.id, "part_id": "tool"}
            )
            packets.append(
                Packet(
                    identity=call_identity,
                    obj=OperationStatus(status=RunStatus.RUNNING, tool_name=call.name),
                )
            )
            record = records.get((identity.message_id, call.id))
            tool = tools.get(record.tool_id) if record is not None else None
            result = results.get(call.id)
            content: list[Packet] = []
            if result is not None and record is not None:
                result = restore_tool_result(result, record, tool)
            for progress in tool_display_progress(
                call, result, tool_id=record.tool_id if record else None
            ):
                obj = project_tool_progress(progress)
                if obj is not None:
                    content.append(Packet(identity=call_identity, obj=obj))
            children = [
                child
                for child in transcript.child_runs
                if child.parent_message_id == identity.message_id
                and child.parent_tool_call_id == call.id
            ]
            if content:
                packets.append(
                    content[0].model_copy(update={"identity": call_identity})
                )
            for child in children:
                child_mode = (
                    PresentationMode.CODING_THINKING
                    if tool is not None
                    and tool.in_code_tool_id == CodingAgentTool.__name__
                    else PresentationMode.ANSWER
                )
                packets.extend(
                    _execution_run_packets(
                        child,
                        response_id,
                        records,
                        tools,
                        settings,
                        documents,
                        child_mode,
                    )
                )
            packets.extend(
                packet.model_copy(update={"identity": call_identity})
                for packet in content[1:]
                if not isinstance(packet.obj, SectionEnd)
            )
            tool_operation = next(
                (
                    item
                    for item in transcript.operations
                    if item.message_index == operation.message_index
                    and item.tool_call_id == call.id
                ),
                None,
            )
            status = (
                tool_operation.status
                if tool_operation is not None
                else transcript.status
            )
            packets.append(
                Packet(
                    identity=call_identity,
                    obj=OperationStatus(status=status, tool_name=call.name),
                )
            )
            if status != RunStatus.RUNNING:
                packets.append(Packet(identity=call_identity, obj=SectionEnd()))
    packets.append(
        Packet(
            identity=base.model_copy(update={"part_id": "run"}),
            obj=OperationStatus(status=transcript.status),
        )
    )
    if transcript.parent_run_id is None and transcript.status != RunStatus.RUNNING:
        packets.append(
            Packet(
                identity=base.model_copy(update={"part_id": "run"}),
                obj=OverallStop(
                    stop_reason="user_cancelled"
                    if transcript.status == RunStatus.CANCELLED
                    else "finished"
                ),
            )
        )
    return packets
