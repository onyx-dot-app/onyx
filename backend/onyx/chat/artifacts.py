from collections.abc import Callable

from onyx.chat.chat_state import ChatArtifactSnapshot, ChatStateContainer, SearchDocKey
from onyx.chat.citation_processor import (
    CitationMapping,
    CitationMode,
    DynamicCitationProcessor,
)
from onyx.chat.citation_utils import (
    build_context_file_citation_mapping,
    update_citation_processor_from_tool_result,
)
from onyx.context.search.models import SearchDoc, SearchDocsResponse
from onyx.file_store.models import ExtractedContextFiles
from onyx.llm.models import AssistantMessage, Message, ToolCall, ToolResultMessage
from onyx.server.query_and_chat.placement import Placement
from onyx.tools.built_in_tools import STOPPING_TOOLS_NAMES
from onyx.tools.interface import Tool
from onyx.tools.models import (
    ChatFile,
    CustomToolCallSummary,
    CustomToolUserFileSnapshot,
    MemoryToolResponseSnapshot,
    PythonToolRichResponse,
    ToolCallInfo,
)
from onyx.tools.tool_implementations.file_reader.file_reader_tool import FileReadResult
from onyx.tools.tool_implementations.images.models import FinalImageGenerationResponse
from onyx.tools.tool_implementations.search.search_tool import SearchTool


class ChatSearchResult(SearchDocsResponse):
    """Search documents with files staged before the tool result is committed."""

    staged_files: list[ChatFile]


class ChatArtifacts:
    """Rich tool results, citation state, and persistence for one chat request."""

    def __init__(
        self,
        files: ExtractedContextFiles,
        chat_files: list[ChatFile],
        include_citations: bool,
    ) -> None:
        self.chat_files = list(chat_files)
        self.citation_processor = DynamicCitationProcessor(
            citation_mode=CitationMode.HYPERLINK
            if include_citations
            else CitationMode.REMOVE
        )
        initial = (
            build_context_file_citation_mapping(files.file_metadata)
            if files.file_metadata
            else {}
        )
        self.initial_citations = initial
        self.citation_processor.update_citation_mapping(initial)
        self.gathered_documents = list(initial.values())
        self.citation_mapping: dict[int, str] = {}
        self.has_called_search_tool = False
        self.ran_image_gen = False

    def update_context(
        self,
        message: AssistantMessage,
        responses: list[ToolResultMessage],
    ) -> None:
        """Apply completed-turn artifacts to the next request's context policy."""
        for response in responses:
            data = response.details
            if response.tool_name == SearchTool.NAME:
                self.has_called_search_tool = True
            if isinstance(data, SearchDocsResponse):
                self.citation_mapping.update(data.citation_mapping)
                self.gathered_documents.extend(data.search_docs)
            if isinstance(data, ChatSearchResult):
                existing = {file.filename for file in self.chat_files}
                self.chat_files.extend(
                    file for file in data.staged_files if file.filename not in existing
                )
            update_citation_processor_from_tool_result(
                response, self.citation_processor
            )
        self.ran_image_gen = self.ran_image_gen or any(
            call.name in STOPPING_TOOLS_NAMES for call in message.tool_calls
        )

    def project(
        self,
        messages: list[Message],
        tools: list[Tool],
        placement_for: Callable[[str], Placement],
    ) -> ChatArtifactSnapshot:
        return project_tool_artifacts(
            messages, tools, placement_for, self.initial_citations
        )


def _saved_tool_response(result: ToolResultMessage) -> str:
    data = result.details
    if isinstance(
        data, (MemoryToolResponseSnapshot, CustomToolCallSummary, FileReadResult)
    ):
        return data.model_dump_json()
    return result.text


def project_tool_artifacts(
    messages: list[Message],
    tools: list[Tool],
    placement_for: Callable[[str], Placement],
    initial_citations: CitationMapping | None = None,
) -> ChatArtifactSnapshot:
    """Build persistence records without changing policy state or performing I/O."""
    tools_by_name = {tool.name: tool for tool in tools}
    records: list[ToolCallInfo] = []
    documents: dict[SearchDocKey, SearchDoc] = {}
    citations = DynamicCitationProcessor(citation_mode=CitationMode.HYPERLINK)
    citations.update_citation_mapping(initial_citations or {})
    assistant: AssistantMessage | None = None
    for message in messages:
        if isinstance(message, AssistantMessage):
            assistant = message
        elif isinstance(message, ToolResultMessage) and assistant is not None:
            tool = tools_by_name.get(message.tool_name)
            if tool is None:
                continue
            call = next(
                call for call in assistant.tool_calls if call.id == message.tool_call_id
            )
            records.append(
                _tool_record(
                    tool,
                    assistant,
                    message,
                    call,
                    placement_for(call.id),
                )
            )
            data = message.details
            if isinstance(data, SearchDocsResponse):
                for document in data.search_docs:
                    documents.setdefault(
                        ChatStateContainer.create_search_doc_key(document), document
                    )
            update_citation_processor_from_tool_result(message, citations)
    return ChatArtifactSnapshot(
        tool_calls=records,
        all_search_docs=documents,
        citation_to_doc=citations.citation_to_doc,
    )


def _tool_record(
    tool: Tool,
    output: AssistantMessage,
    tool_response: ToolResultMessage,
    tool_call: ToolCall,
    placement: Placement,
) -> ToolCallInfo:
    data = tool_response.details
    search_docs = data.search_docs if isinstance(data, SearchDocsResponse) else None
    displayed_docs = (
        data.displayed_docs if isinstance(data, SearchDocsResponse) else None
    )
    generated_images = None
    if isinstance(data, FinalImageGenerationResponse):
        generated_images = data.generated_images

    generated_files = None
    if isinstance(data, PythonToolRichResponse):
        generated_files = data.generated_files or None

    # Custom tools save image/CSV blobs and return their ids.
    generated_file_ids = None
    if isinstance(data, CustomToolCallSummary) and isinstance(
        data.tool_result, CustomToolUserFileSnapshot
    ):
        generated_file_ids = data.tool_result.file_ids or None

    saved_response = _saved_tool_response(tool_response)

    return ToolCallInfo(
        parent_tool_call_id=None,  # Top-level tool calls are attached to the chat message
        turn_index=placement.turn_index,
        tab_index=placement.tab_index,
        tool_name=tool_call.name,
        tool_call_id=tool_call.id,
        tool_id=tool.id,
        reasoning_tokens=output.thinking,  # Calls from one assistant message share its thinking.
        tool_call_arguments=tool_call.arguments,
        tool_call_response=saved_response,
        search_docs=displayed_docs or search_docs,
        generated_images=generated_images,
        generated_files=generated_files,
        generated_file_ids=generated_file_ids,
    )
