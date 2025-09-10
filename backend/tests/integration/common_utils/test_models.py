from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel
from pydantic import Field

from onyx.auth.schemas import UserRole
from onyx.configs.constants import QAFeedbackType
from onyx.context.search.enums import RecencyBiasSetting
from onyx.context.search.models import SavedSearchDoc
from onyx.db.enums import AccessType
from onyx.server.documents.models import DocumentSource
from onyx.server.documents.models import IndexAttemptSnapshot
from onyx.server.documents.models import IndexingStatus
from onyx.server.documents.models import InputType

"""
These data models are used to represent the data on the testing side of things.
This means the flow is:
1. Make request that changes data in db
2. Make a change to the testing model
3. Retrieve data from db
4. Compare db data with testing model to verify
"""


class DATestAPIKey(BaseModel):
    api_key_id: int
    api_key_display: str
    api_key: str | None = None  # only present on initial creation
    api_key_name: str | None = None
    api_key_role: UserRole

    user_id: UUID
    headers: dict


class DATestUser(BaseModel):
    id: str
    email: str
    password: str
    headers: dict
    role: UserRole
    is_active: bool
    cookies: dict = {}


class DATestPersonaLabel(BaseModel):
    id: int | None = None
    name: str


class DATestCredential(BaseModel):
    id: int
    name: str
    credential_json: dict[str, Any]
    admin_public: bool
    source: DocumentSource
    curator_public: bool
    groups: list[int]


class DATestConnector(BaseModel):
    id: int
    name: str
    source: DocumentSource
    input_type: InputType
    connector_specific_config: dict[str, Any]
    groups: list[int] | None = None
    access_type: AccessType | None = None


class SimpleTestDocument(BaseModel):
    id: str
    content: str
    image_file_id: str | None = None


class DATestCCPair(BaseModel):
    id: int
    name: str
    connector_id: int
    credential_id: int
    access_type: AccessType
    groups: list[int]
    documents: list[SimpleTestDocument] = Field(default_factory=list)


class DATestUserGroup(BaseModel):
    id: int
    name: str
    user_ids: list[str]
    cc_pair_ids: list[int]


class DATestLLMProvider(BaseModel):
    id: int
    name: str
    provider: str
    api_key: str
    default_model_name: str
    is_public: bool
    groups: list[int]
    api_base: str | None = None
    api_version: str | None = None


class DATestDocumentSet(BaseModel):
    id: int
    name: str
    description: str
    cc_pair_ids: list[int] = Field(default_factory=list)
    is_public: bool
    is_up_to_date: bool
    users: list[str] = Field(default_factory=list)
    groups: list[int] = Field(default_factory=list)
    federated_connectors: list[dict[str, Any]] = Field(default_factory=list)


class DATestPersona(BaseModel):
    id: int
    name: str
    description: str
    num_chunks: float
    llm_relevance_filter: bool
    is_public: bool
    llm_filter_extraction: bool
    recency_bias: RecencyBiasSetting
    document_set_ids: list[int]
    tool_ids: list[int]
    llm_model_provider_override: str | None
    llm_model_version_override: str | None
    users: list[str]
    groups: list[int]
    label_ids: list[int]

    # Embedded prompt fields (no longer separate prompt_ids)
    system_prompt: str | None = None
    task_prompt: str | None = None
    datetime_aware: bool = True


class DATestChatMessage(BaseModel):
    id: int
    chat_session_id: UUID
    parent_message_id: int | None
    message: str


class DATestChatSession(BaseModel):
    id: UUID
    persona_id: int
    description: str


class DAQueryHistoryEntry(DATestChatSession):
    feedback_type: QAFeedbackType | None


class ToolName(str, Enum):
    INTERNET_SEARCH = "internet_search"
    INTERNAL_SEARCH = "run_search"
    IMAGE_GENERATION = "generate_image"


class ToolResult(BaseModel):
    tool_name: ToolName

    queries: list[str] = Field(default_factory=list)
    documents: list[SavedSearchDoc] = Field(default_factory=list)


class StreamedResponse(BaseModel):
    full_message: str = ""
    top_documents: list[SavedSearchDoc] | None = None
    used_tools: list[ToolResult] = Field(default_factory=list)

    # Track heartbeat packets for image generation and other tools
    heartbeat_packets: list[dict[str, Any]] = Field(default_factory=list)


class DATestGatingType(str, Enum):
    FULL = "full"
    PARTIAL = "partial"
    NONE = "none"


class DATestSettings(BaseModel):
    """General settings"""

    # is float to allow for fractional days for easier automated testing
    maximum_chat_retention_days: float | None = None
    gpu_enabled: bool | None = None
    product_gating: DATestGatingType = DATestGatingType.NONE
    anonymous_user_enabled: bool | None = None
    image_extraction_and_analysis_enabled: bool | None = False
    search_time_image_analysis_enabled: bool | None = False


@dataclass
class DATestIndexAttempt:
    id: int
    status: IndexingStatus | None
    new_docs_indexed: int | None
    total_docs_indexed: int | None
    docs_removed_from_index: int | None
    error_msg: str | None
    time_started: datetime | None
    time_updated: datetime | None

    @classmethod
    def from_index_attempt_snapshot(
        cls, index_attempt: IndexAttemptSnapshot
    ) -> "DATestIndexAttempt":
        return cls(
            id=index_attempt.id,
            status=index_attempt.status,
            new_docs_indexed=index_attempt.new_docs_indexed,
            total_docs_indexed=index_attempt.total_docs_indexed,
            docs_removed_from_index=index_attempt.docs_removed_from_index,
            error_msg=index_attempt.error_msg,
            time_started=(
                datetime.fromisoformat(index_attempt.time_started)
                if index_attempt.time_started
                else None
            ),
            time_updated=datetime.fromisoformat(index_attempt.time_updated),
        )
