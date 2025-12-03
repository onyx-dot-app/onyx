import dataclasses
from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

from pydantic import BaseModel
from redis.client import Redis
from sqlalchemy.orm import Session

from onyx.chat.emitter import Emitter
from onyx.chat.models import PromptConfig
from onyx.context.search.models import InferenceSection
from onyx.db.models import User
from onyx.file_store.models import InMemoryChatFile
from onyx.llm.interfaces import LLM
from onyx.server.query_and_chat.streaming_models import CitationInfo
from onyx.tools.tool import Tool


@dataclass
class ChatTurnDependencies:
    llm: LLM
    db_session: Session
    tools: Sequence[Tool]
    redis_client: Redis
    emitter: Emitter
    user_or_none: User | None
    prompt_config: PromptConfig


class FetchedDocumentCacheEntry(BaseModel):
    inference_section: InferenceSection
    document_citation_number: int


@dataclass
class ChatTurnContext:
    """Context class to hold search tool and other dependencies"""

    chat_session_id: UUID
    message_id: int
    run_dependencies: ChatTurnDependencies
    current_run_step: int = 0
    should_cite_documents: bool = False
    documents_processed_by_citation_context_handler: int = 0
    tool_calls_processed_by_citation_context_handler: int = 0
    fetched_documents_cache: dict[str, FetchedDocumentCacheEntry] = dataclasses.field(
        default_factory=dict
    )
    citations: list[CitationInfo] = dataclasses.field(default_factory=list)

    # Files uploaded by the user in the chat
    chat_files: list[InMemoryChatFile] = dataclasses.field(default_factory=list)

    # Token count of all current input context (system, history, user message, agent turns, etc.)
    # Updated dynamically as the conversation progresses through tool calls
    current_input_tokens: int = 0
