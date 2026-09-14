import threading
from collections.abc import Callable
from contextlib import nullcontext
from copy import deepcopy
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from onyx.agents.runtime import Agent
from onyx.agents.transcript import AgentTranscript
from onyx.cache.interface import CacheBackend
from onyx.chat.citation_processor import CitationMapping
from onyx.chat.models import AnswerStreamPart, SearchParams
from onyx.context.search.models import SearchDoc
from onyx.db.enums import IncognitoRecordMode
from onyx.db.memory import UserMemoryContext
from onyx.file_store.models import ExtractedContextFiles, FileToolMetadata
from onyx.llm.interfaces import LLM, LLMUserIdentity
from onyx.llm.models import GenerationRequestParams, Message, ReasoningEffort
from onyx.onyxbot.slack.models import SlackContext
from onyx.server.query_and_chat.models import SendMessageRequest
from onyx.tools.models import ChatFile, ToolCallInfo

# A full key preserves distinct highlights for the same document chunk.
SearchDocKey = str | tuple[str, int, tuple[str, ...]]


class ChatArtifactSnapshot(BaseModel):
    """Application records derived from accepted tool results."""

    model_config = ConfigDict(frozen=True)

    tool_calls: list[ToolCallInfo]
    all_search_docs: dict[SearchDocKey, SearchDoc]
    citation_to_doc: CitationMapping


class ChatResponseSnapshot(BaseModel):
    """Detached response data for one persistence attempt."""

    model_config = ConfigDict(frozen=True)

    answer_tokens: str | None
    reasoning_tokens: str | None
    request_params: GenerationRequestParams | None
    citation_to_doc: CitationMapping
    tool_calls: list[ToolCallInfo]
    is_clarification: bool
    all_search_docs: dict[SearchDocKey, SearchDoc]
    emitted_citations: set[int]
    pre_answer_processing_time: float | None
    transcript: AgentTranscript | None
    cancelled: bool


class ChatStateContainer:
    """Collect display output and artifacts for complete or partial persistence.

    Runtime commits and subscribers share the bound agent lock. Snapshots acquire
    that lock before the display lock, so both describe the same committed event.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._agent: Agent | None = None
        self._project_artifacts: (
            Callable[[list[Message]], ChatArtifactSnapshot] | None
        ) = None
        self.reasoning_tokens: str | None = None
        self.answer_tokens: str | None = None
        self.citation_to_doc: CitationMapping = {}
        self.is_clarification: bool = False
        self.pre_answer_processing_time: float | None = None
        self.request_params: GenerationRequestParams | None = None
        self._emitted_citations: set[int] = set()

    def bind_agent(
        self,
        agent: Agent,
        project_artifacts: Callable[[list[Message]], ChatArtifactSnapshot]
        | None = None,
    ) -> None:
        """Bind runtime history and artifact projection for consistent snapshots."""
        with self._lock:
            self._agent = agent
            self._project_artifacts = project_artifacts

    def update_display(
        self,
        *,
        answer: str,
        reasoning: str,
        request_params: GenerationRequestParams | None,
        citations: set[int],
        pre_answer_seconds: float | None = None,
    ) -> None:
        """Commit all display fields for one generation event together."""
        with self._lock:
            self.answer_tokens = answer
            self.reasoning_tokens = reasoning
            self.request_params = deepcopy(request_params)
            self._emitted_citations.update(citations)
            if pre_answer_seconds is not None:
                self.pre_answer_processing_time = pre_answer_seconds

    def snapshot(self, *, cancelled: bool = False) -> ChatResponseSnapshot:
        """Capture runtime history and display output at one commit boundary."""
        while True:
            with self._lock:
                agent = self._agent
            with agent.state_lock if agent is not None else nullcontext():
                with self._lock:
                    if agent is not self._agent:
                        continue
                    artifacts = (
                        self._project_artifacts(agent.output_messages)
                        if agent is not None and self._project_artifacts is not None
                        else None
                    )
                    return ChatResponseSnapshot(
                        answer_tokens=self.answer_tokens,
                        reasoning_tokens=self.reasoning_tokens,
                        request_params=deepcopy(self.request_params),
                        citation_to_doc=deepcopy(
                            artifacts.citation_to_doc
                            if artifacts
                            else self.citation_to_doc
                        ),
                        tool_calls=deepcopy(artifacts.tool_calls if artifacts else []),
                        is_clarification=self.is_clarification,
                        all_search_docs=deepcopy(
                            artifacts.all_search_docs if artifacts else {}
                        ),
                        emitted_citations=self._emitted_citations.copy(),
                        pre_answer_processing_time=self.pre_answer_processing_time,
                        transcript=agent.snapshot(cancelled=cancelled)
                        if agent
                        else None,
                        cancelled=cancelled,
                    )

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
            self.citation_to_doc = deepcopy(citation_to_doc)

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
        return self.snapshot().tool_calls

    def get_citation_to_doc(self) -> CitationMapping:
        """Thread-safe getter for citation_to_doc (returns a copy)."""
        return self.snapshot().citation_to_doc

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


class PersonaPromptConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    system_prompt: str | None
    task_prompt: str | None
    datetime_aware: bool
    replace_base_system_prompt: bool


class PreparedModel(BaseModel):
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    llm: LLM
    message_id: int
    display_name: str


class ChatTurnSetup(BaseModel):
    """Request values and service references shared by model executions."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    initial_packets: list[AnswerStreamPart]
    new_msg_req: SendMessageRequest
    chat_session_id: UUID
    chat_session_project_id: int | None
    # The session's pinned recording policy. None is an ordinary chat.
    incognito_record_mode: IncognitoRecordMode | None
    persona_id: int
    persona: PersonaPromptConfig
    user_message_id: int
    user_identity: LLMUserIdentity
    models: list[PreparedModel]
    messages: list[Message]
    extracted_context_files: ExtractedContextFiles
    # Processing-fence value and stream-buffer key — single source for the run id
    processing_run_id: int
    reserved_token_count: int
    reasoning_effort: ReasoningEffort
    search_params: SearchParams
    all_injected_file_metadata: dict[str, FileToolMetadata]
    available_files: AvailableFiles
    forced_tool_id: int | None
    chat_files_for_tools: list[ChatFile]
    custom_agent_prompt: str | None
    user_memory_context: UserMemoryContext
    # For deep research: was the last assistant message a clarification request?
    skip_clarification: bool
    cache: CacheBackend
    # Execution params forwarded to per-model tool construction
    slack_context: SlackContext | None
    custom_tool_additional_headers: dict[str, str] | None
    mcp_headers: dict[str, str] | None
