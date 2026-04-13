import threading
from collections.abc import Callable
from dataclasses import dataclass
from uuid import UUID

from pydantic import BaseModel

from onyx.cache.interface import CacheBackend
from onyx.chat.citation_processor import CitationMapping
from onyx.chat.models import ChatLoadedFile
from onyx.chat.models import ChatMessageSimple
from onyx.chat.models import ExtractedContextFiles
from onyx.chat.models import FileToolMetadata
from onyx.chat.models import SearchParams
from onyx.context.search.models import SearchDoc
from onyx.db.memory import UserMemoryContext
from onyx.db.models import ChatMessage
from onyx.db.models import ChatSession
from onyx.db.models import Persona
from onyx.llm.interfaces import LLM
from onyx.llm.interfaces import LLMUserIdentity
from onyx.onyxbot.slack.models import SlackContext
from onyx.server.query_and_chat.models import SendMessageRequest
from onyx.tools.models import ChatFile
from onyx.tools.models import ToolCallInfo

# Type alias for search doc deduplication key
# Simple key: just document_id (str)
# Full key: (document_id, chunk_ind, match_highlights)
SearchDocKey = str | tuple[str, int, tuple[str, ...]]


class ChatStateContainer:
    """Container for accumulating state during LLM loop execution.

    This container holds the partial state that can be saved to the database
    if the generation is stopped by the user or completes normally.

    Thread-safe: All write operations are protected by a lock to ensure safe
    concurrent access from multiple threads. For thread-safe reads, use the
    getter methods. Direct attribute access is not thread-safe.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # These are collected at the end after the entire tool call is completed
        self.tool_calls: list[ToolCallInfo] = []
        # This is accumulated during the streaming
        self.reasoning_tokens: str | None = None
        # This is accumulated during the streaming of the answer
        self.answer_tokens: str | None = None
        # Store citation mapping for building citation_docs_info during partial saves
        self.citation_to_doc: CitationMapping = {}
        # True if this turn is a clarification question (deep research flow)
        self.is_clarification: bool = False
        # Pre-answer processing time (time before answer starts) in seconds
        self.pre_answer_processing_time: float | None = None
        # Note: LLM cost tracking is now handled in multi_llm.py
        # Search doc collection - maps dedup key to SearchDoc for all docs from tool calls
        self._all_search_docs: dict[SearchDocKey, SearchDoc] = {}
        # Track which citation numbers were actually emitted during streaming
        self._emitted_citations: set[int] = set()

    def add_tool_call(self, tool_call: ToolCallInfo) -> None:
        """Add a tool call to the accumulated state."""
        with self._lock:
            self.tool_calls.append(tool_call)

    def set_reasoning_tokens(self, reasoning: str | None) -> None:
        """Set the reasoning tokens from the final answer generation."""
        with self._lock:
            self.reasoning_tokens = reasoning

    def set_answer_tokens(self, answer: str | None) -> None:
        """Set the answer tokens from the final answer generation."""
        with self._lock:
            self.answer_tokens = answer

    def set_citation_mapping(self, citation_to_doc: CitationMapping) -> None:
        """Set the citation mapping from citation processor."""
        with self._lock:
            self.citation_to_doc = citation_to_doc

    def set_is_clarification(self, is_clarification: bool) -> None:
        """Set whether this turn is a clarification question."""
        with self._lock:
            self.is_clarification = is_clarification

    def get_answer_tokens(self) -> str | None:
        """Thread-safe getter for answer_tokens."""
        with self._lock:
            return self.answer_tokens

    def get_reasoning_tokens(self) -> str | None:
        """Thread-safe getter for reasoning_tokens."""
        with self._lock:
            return self.reasoning_tokens

    def get_tool_calls(self) -> list[ToolCallInfo]:
        """Thread-safe getter for tool_calls (returns a copy)."""
        with self._lock:
            return self.tool_calls.copy()

    def get_citation_to_doc(self) -> CitationMapping:
        """Thread-safe getter for citation_to_doc (returns a copy)."""
        with self._lock:
            return self.citation_to_doc.copy()

    def get_is_clarification(self) -> bool:
        """Thread-safe getter for is_clarification."""
        with self._lock:
            return self.is_clarification

    def set_pre_answer_processing_time(self, duration: float | None) -> None:
        """Set the pre-answer processing time (time before answer starts)."""
        with self._lock:
            self.pre_answer_processing_time = duration

    def get_pre_answer_processing_time(self) -> float | None:
        """Thread-safe getter for pre_answer_processing_time."""
        with self._lock:
            return self.pre_answer_processing_time

    @staticmethod
    def create_search_doc_key(
        search_doc: SearchDoc, use_simple_key: bool = True
    ) -> SearchDocKey:
        """Create a unique key for a SearchDoc for deduplication.

        Args:
            search_doc: The SearchDoc to create a key for
            use_simple_key: If True (default), use only document_id for deduplication.
                If False, include chunk_ind and match_highlights so that the same
                document/chunk with different highlights are stored separately.
        """
        if use_simple_key:
            return search_doc.document_id
        match_highlights_tuple = tuple(sorted(search_doc.match_highlights or []))
        return (search_doc.document_id, search_doc.chunk_ind, match_highlights_tuple)

    def add_search_docs(
        self, search_docs: list[SearchDoc], use_simple_key: bool = True
    ) -> None:
        """Add search docs to the accumulated collection with deduplication.

        Args:
            search_docs: List of SearchDoc objects to add
            use_simple_key: If True (default), deduplicate by document_id only.
                If False, deduplicate by document_id + chunk_ind + match_highlights.
        """
        with self._lock:
            for doc in search_docs:
                key = self.create_search_doc_key(doc, use_simple_key)
                if key not in self._all_search_docs:
                    self._all_search_docs[key] = doc

    def get_all_search_docs(self) -> dict[SearchDocKey, SearchDoc]:
        """Thread-safe getter for all accumulated search docs (returns a copy)."""
        with self._lock:
            return self._all_search_docs.copy()

    def add_emitted_citation(self, citation_num: int) -> None:
        """Add a citation number that was actually emitted during streaming."""
        with self._lock:
            self._emitted_citations.add(citation_num)

    def get_emitted_citations(self) -> set[int]:
        """Thread-safe getter for emitted citations (returns a copy)."""
        with self._lock:
            return self._emitted_citations.copy()


class AvailableFiles(BaseModel):
    """Separated file IDs for the FileReaderTool so it knows which loader to use."""

    # IDs from the ``user_file`` table (project / persona-attached files).
    user_file_ids: list[UUID] = []
    # IDs from the ``file_record`` table (chat-attached files).
    chat_file_ids: list[UUID] = []


@dataclass(frozen=True)
class ChatTurnSetup:
    """Immutable context produced by ``build_chat_turn`` and consumed by ``_run_models``."""

    new_msg_req: SendMessageRequest
    chat_session: ChatSession
    persona: Persona
    user_message: ChatMessage
    user_identity: LLMUserIdentity
    llms: list[LLM]  # length 1 for single-model, N for multi-model
    model_display_names: list[str]  # parallel to llms
    simple_chat_history: list[ChatMessageSimple]
    extracted_context_files: ExtractedContextFiles
    reserved_messages: list[ChatMessage]  # length 1 for single, N for multi
    reserved_token_count: int
    search_params: SearchParams
    all_injected_file_metadata: dict[str, FileToolMetadata]
    available_files: AvailableFiles
    tool_id_to_name_map: dict[int, str]
    forced_tool_id: int | None
    files: list[ChatLoadedFile]
    chat_files_for_tools: list[ChatFile]
    custom_agent_prompt: str | None
    user_memory_context: UserMemoryContext
    # For deep research: was the last assistant message a clarification request?
    skip_clarification: bool
    check_is_connected: Callable[[], bool]
    cache: CacheBackend
    # Execution params forwarded to per-model tool construction
    bypass_acl: bool
    slack_context: SlackContext | None
    custom_tool_additional_headers: dict[str, str] | None
    mcp_headers: dict[str, str] | None
