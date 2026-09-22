from collections.abc import Mapping

from pydantic import BaseModel, field_serializer, field_validator

from onyx.agents.models import RunSnapshot
from onyx.chat.citation_processor import CitationMapping, DynamicCitationProcessor
from onyx.chat.citation_utils import (
    build_context_file_citation_mapping,
    update_citation_processor_from_tool_result,
)
from onyx.chat.models import ChatArtifactSnapshot, CitationMode
from onyx.context.search.models import SearchDoc, SearchDocsResponse
from onyx.deep_research.models import ResearchAgentCallResult
from onyx.file_store.models import ExtractedContextFiles
from onyx.llm.models import AssistantMessage, ToolCall, ToolResultMessage
from onyx.tools.built_in_tools import STOPPING_TOOLS_NAMES
from onyx.tools.file_snapshot import SavedChatFile
from onyx.tools.models import (
    ChatFile,
    CustomToolCallSummary,
    CustomToolUserFileSnapshot,
    LlmPythonExecutionResult,
    ToolCallInfo,
)
from onyx.tools.tool_implementations.images.models import FinalImageGenerationResponse
from onyx.tools.tool_implementations.search.search_tool import SearchTool


class ChatSearchResult(SearchDocsResponse):
    """Search documents with files staged before the tool result is committed."""

    staged_files: list[ChatFile]

    @field_serializer("staged_files")
    def serialize_staged_files(self, files: list[ChatFile]) -> list[SavedChatFile]:
        return [SavedChatFile.capture(file) for file in files]

    @field_validator("staged_files", mode="before")
    @classmethod
    def restore_staged_files(cls, value: object) -> list[ChatFile]:
        if not isinstance(value, list):
            raise ValueError("Staged files must be a list")
        return [
            file
            if isinstance(file, ChatFile)
            else SavedChatFile.model_validate(file).restore()
            for file in value
        ]


class ChatArtifacts:
    """Tool-derived context for subsequent chat steps."""

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
        """Apply accepted tool results to the next request's context policy."""
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


def _saved_tool_metadata(result: ToolResultMessage) -> BaseModel | None:
    data = result.details
    if isinstance(data, SearchDocsResponse):
        # Documents are stored through the tool call's search-document relation.
        return SearchDocsResponse(
            queries=data.queries,
            sources=data.sources,
            time_filter_start=data.time_filter_start,
            time_filter_end=data.time_filter_end,
            search_docs=[],
            citation_mapping=data.citation_mapping,
        )
    return data


def project_tool_artifacts(
    snapshot: RunSnapshot,
    tool_ids: Mapping[str, int],
    initial_citations: CitationMapping | None = None,
) -> ChatArtifactSnapshot:
    """Project completed and interrupted operations from one execution tree."""
    records: list[ToolCallInfo] = []
    documents: dict[str, SearchDoc] = {}
    citations = DynamicCitationProcessor(citation_mode=CitationMode.HYPERLINK)
    citations.update_citation_mapping(initial_citations or {})
    for operation in snapshot.operations:
        if operation.tool_call_id is not None:
            continue
        message = snapshot.messages[operation.message_index]
        if not isinstance(message, AssistantMessage):
            raise ValueError(
                "Message operation does not reference an assistant message"
            )
        results: dict[str, ToolResultMessage] = {}
        for item in snapshot.messages[operation.message_index + 1 :]:
            if isinstance(item, AssistantMessage):
                break
            if isinstance(item, ToolResultMessage):
                results[item.tool_call_id] = item
        for index, call in enumerate(message.tool_calls):
            tool_id = tool_ids.get(call.name)
            if tool_id is None:
                continue
            result = results.get(call.id)
            records.append(
                _tool_record(
                    tool_id,
                    message,
                    result,
                    call,
                    snapshot,
                    operation.step_index,
                    index,
                )
            )
            if result is None:
                continue
            if isinstance(result.details, SearchDocsResponse):
                for document in result.details.search_docs:
                    documents.setdefault(document.document_id, document)
            if isinstance(result.details, ResearchAgentCallResult):
                citations.update_citation_mapping(result.details.citation_mapping)
                for document in result.details.citation_mapping.values():
                    documents.setdefault(document.document_id, document)
            update_citation_processor_from_tool_result(result, citations)
    for child in snapshot.child_runs:
        child_artifacts = project_tool_artifacts(child, tool_ids)
        records.extend(child_artifacts.tool_calls)
        documents.update(child_artifacts.all_search_docs)
    return ChatArtifactSnapshot(
        tool_calls=records,
        all_search_docs=documents,
        citation_to_doc=citations.citation_to_doc,
    )


def _tool_record(
    tool_id: int,
    output: AssistantMessage,
    tool_response: ToolResultMessage | None,
    tool_call: ToolCall,
    snapshot: RunSnapshot,
    turn: int,
    index: int,
) -> ToolCallInfo:
    data = tool_response.details if tool_response else None
    search_docs = data.search_docs if isinstance(data, SearchDocsResponse) else None
    displayed_docs = (
        data.displayed_docs if isinstance(data, SearchDocsResponse) else None
    )
    generated_images = None
    if isinstance(data, FinalImageGenerationResponse):
        generated_images = data.generated_images

    generated_files = None
    if isinstance(data, LlmPythonExecutionResult):
        generated_files = data.generated_files or None

    # Custom tools save image/CSV blobs and return their ids.
    generated_file_ids = None
    if isinstance(data, CustomToolCallSummary) and isinstance(
        data.tool_result, CustomToolUserFileSnapshot
    ):
        generated_file_ids = data.tool_result.file_ids or None

    saved_metadata = _saved_tool_metadata(tool_response) if tool_response else None

    return ToolCallInfo(
        message_id=output.id or f"{snapshot.run_id}:{turn}",
        parent_message_id=snapshot.parent_message_id,
        parent_tool_call_id=snapshot.parent_tool_call_id,
        turn_index=turn,
        tab_index=index,
        tool_name=tool_call.name,
        tool_call_id=tool_call.id,
        tool_id=tool_id,
        reasoning_tokens=output.thinking,  # Calls from one assistant message share its thinking.
        tool_call_arguments=tool_call.arguments,
        tool_call_response=tool_response.text if tool_response else "",
        result_metadata=saved_metadata,
        search_docs=displayed_docs or search_docs,
        generated_images=generated_images,
        generated_files=generated_files,
        generated_file_ids=generated_file_ids,
    )
