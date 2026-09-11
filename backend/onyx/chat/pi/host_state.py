"""Versioned JSON state for stateless Onyx callbacks during a Pi run."""

import base64
from typing import Any, Literal, Self

from pydantic import BaseModel, model_validator

from onyx.chat.chat_state import ChatStateContainer
from onyx.chat.citation_processor import CitationMode, DynamicCitationProcessor
from onyx.chat.models import (
    ChatLoadedFile,
    ChatMessageSimple,
    ExtractedContextFiles,
    LlmStepResult,
)
from onyx.context.search.models import SearchDoc
from onyx.file_store.file_store import get_default_file_store
from onyx.llm.interfaces import ToolChoiceOptions
from onyx.llm.model_response import Usage
from onyx.tools.models import ChatFile, ToolCallInfo, ToolCallKickoff
from shared_configs.contextvars import (
    CURRENT_TENANT_ID_CONTEXTVAR,
    get_current_tenant_id,
)


class ChatFileSnapshot(BaseModel):
    filename: str
    source_file_id: str | None = None
    content_base64: str | None = None

    @model_validator(mode="after")
    def validate_source(self) -> Self:
        if (self.source_file_id is None) == (self.content_base64 is None):
            raise ValueError("A tool file must have exactly one source")
        return self

    @classmethod
    def capture(cls, file: ChatFile) -> "ChatFileSnapshot":
        if file.source_file_id is not None:
            return cls(filename=file.filename, source_file_id=file.source_file_id)
        return cls(
            filename=file.filename,
            content_base64=base64.b64encode(file.content).decode("ascii"),
        )

    def restore(self) -> ChatFile:
        if self.source_file_id is not None:
            file_id = self.source_file_id
            tenant_id = get_current_tenant_id()

            def load_content() -> bytes:
                token = CURRENT_TENANT_ID_CONTEXTVAR.set(tenant_id)
                try:
                    with get_default_file_store().read_file(
                        file_id, mode="b"
                    ) as content:
                        return content.read()
                finally:
                    CURRENT_TENANT_ID_CONTEXTVAR.reset(token)

            return ChatFile.lazy_from_filename(
                filename=self.filename, loader=load_content, source_file_id=file_id
            )
        assert self.content_base64 is not None
        return ChatFile(
            filename=self.filename,
            content=base64.b64decode(self.content_base64, validate=True),
        )


class ChatLoadedFileSnapshot(BaseModel):
    descriptor: ChatLoadedFile
    content_base64: str

    @classmethod
    def capture(cls, file: ChatLoadedFile) -> "ChatLoadedFileSnapshot":
        return cls(
            descriptor=file.model_copy(update={"content": b""}),
            content_base64=base64.b64encode(file.content).decode("ascii"),
        )

    def restore(self) -> ChatLoadedFile:
        return self.descriptor.model_copy(
            update={"content": base64.b64decode(self.content_base64, validate=True)}
        )


class ChatMessageSnapshot(BaseModel):
    message: ChatMessageSimple
    images: list[ChatLoadedFileSnapshot] | None

    @classmethod
    def capture(cls, message: ChatMessageSimple) -> "ChatMessageSnapshot":
        return cls(
            message=message.model_copy(update={"image_files": None}),
            images=[
                ChatLoadedFileSnapshot.capture(file) for file in message.image_files
            ]
            if message.image_files is not None
            else None,
        )

    def restore(self) -> ChatMessageSimple:
        return self.message.model_copy(
            update={
                "image_files": [file.restore() for file in self.images]
                if self.images is not None
                else None
            }
        )


class ContextFilesSnapshot(BaseModel):
    context: ExtractedContextFiles
    images: list[ChatLoadedFileSnapshot]

    @classmethod
    def capture(cls, context: ExtractedContextFiles) -> "ContextFilesSnapshot":
        return cls(
            context=context.model_copy(update={"image_files": []}),
            images=[
                ChatLoadedFileSnapshot.capture(file) for file in context.image_files
            ],
        )

    def restore(self) -> ExtractedContextFiles:
        return self.context.model_copy(
            update={"image_files": [file.restore() for file in self.images]}
        )


class SearchDocSnapshot(BaseModel):
    document: SearchDoc
    simple_key: bool


class ChatStateSnapshot(BaseModel):
    tool_calls: list[ToolCallInfo]
    reasoning: str | None
    answer: str | None
    citation_to_doc: dict[int, SearchDoc]
    is_clarification: bool
    pre_answer_processing_time: float | None
    request_params: dict[str, Any] | None
    search_docs: list[SearchDocSnapshot]
    emitted_citations: set[int]

    @classmethod
    def capture(cls, state: ChatStateContainer) -> "ChatStateSnapshot":
        return cls(
            tool_calls=state.get_tool_calls(),
            reasoning=state.get_reasoning_tokens(),
            answer=state.get_answer_tokens(),
            citation_to_doc=state.get_citation_to_doc(),
            is_clarification=state.get_is_clarification(),
            pre_answer_processing_time=state.get_pre_answer_processing_time(),
            request_params=state.get_request_params(),
            search_docs=[
                SearchDocSnapshot(document=doc, simple_key=isinstance(key, str))
                for key, doc in state.get_all_search_docs().items()
            ],
            emitted_citations=state.get_emitted_citations(),
        )

    def restore(self, state: ChatStateContainer) -> None:
        """Populate a fresh container owned by one serialized callback."""
        if (
            state.get_tool_calls()
            or state.get_all_search_docs()
            or state.get_emitted_citations()
        ):
            raise ValueError("Chat state must be empty before restoring a snapshot")
        for call in self.tool_calls:
            state.add_tool_call(call)
        state.set_reasoning_tokens(self.reasoning)
        state.set_answer_tokens(self.answer)
        state.set_citation_mapping(self.citation_to_doc.copy())
        state.set_is_clarification(self.is_clarification)
        state.set_pre_answer_processing_time(self.pre_answer_processing_time)
        state.set_request_params(self.request_params)
        for entry in self.search_docs:
            state.add_search_docs([entry.document], use_simple_key=entry.simple_key)
        for citation in self.emitted_citations:
            state.add_emitted_citation(citation)


class CitationSnapshot(BaseModel):
    citation_to_doc: dict[int, SearchDoc]
    seen_citations: dict[int, SearchDoc]
    llm_out: str
    curr_segment: str
    hold: str
    stop_stream: str | None
    citation_mode: CitationMode
    cited_documents_in_order: list[SearchDoc]
    cited_document_ids: set[str]
    recent_cited_documents: set[str]
    non_citation_count: int

    @classmethod
    def capture(cls, citations: DynamicCitationProcessor) -> "CitationSnapshot":
        return cls(
            citation_to_doc=citations.citation_to_doc,
            seen_citations=citations.seen_citations,
            llm_out=citations.llm_out,
            curr_segment=citations.curr_segment,
            hold=citations.hold,
            stop_stream=citations.stop_stream,
            citation_mode=citations.citation_mode,
            cited_documents_in_order=citations.cited_documents_in_order,
            cited_document_ids=citations.cited_document_ids,
            recent_cited_documents=citations.recent_cited_documents,
            non_citation_count=citations.non_citation_count,
        )

    def restore(self) -> DynamicCitationProcessor:
        citations = DynamicCitationProcessor(
            citation_mode=self.citation_mode, stop_stream=self.stop_stream
        )
        citations.citation_to_doc = self.citation_to_doc.copy()
        citations.seen_citations = self.seen_citations.copy()
        citations.llm_out = self.llm_out
        citations.curr_segment = self.curr_segment
        citations.hold = self.hold
        citations.cited_documents_in_order = list(self.cited_documents_in_order)
        citations.cited_document_ids = set(self.cited_document_ids)
        citations.recent_cited_documents = set(self.recent_cited_documents)
        citations.non_citation_count = self.non_citation_count
        return citations


class PendingToolCall(BaseModel):
    id: str
    name: str
    arguments: str


class PresentationSnapshot(BaseModel):
    turn_index: int
    documents: list[SearchDoc] | None
    processing_seconds: float
    reasoning: str
    answer: str
    raw_answer: str
    reasoning_open: bool
    answer_open: bool
    reasoning_sections: int
    calls: list[ToolCallKickoff]
    pending_calls: dict[int, PendingToolCall]
    parser_indices: set[int]
    usage: Usage | None
    finish_reason: str | None


class ChatHostSnapshot(BaseModel):
    version: Literal[1] = 1
    state: ChatStateSnapshot
    citations: CitationSnapshot
    presentation: PresentationSnapshot | None
    simple_chat_history: list[ChatMessageSnapshot]
    chat_files: list[ChatFileSnapshot]
    started_at: float
    forced_tool_id: int | None
    llm_step_result: LlmStepResult
    tool_choice: ToolChoiceOptions
    gathered_documents: list[SearchDoc] | None
    should_cite_documents: bool
    ran_image_gen: bool
    just_ran_web_search: bool
    has_called_search_tool: bool
    code_interpreter_file_generated: bool
    citation_mapping: dict[int, str]
    reasoning_cycles: int
    llm_cycle_count: int
    final_tool_ids: list[int]
    truncated_message_history: list[ChatMessageSnapshot]
    tool_defs: list[dict[str, Any]]
