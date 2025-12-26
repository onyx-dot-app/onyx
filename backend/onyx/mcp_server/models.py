"""Lightweight Pydantic models and enums for MCP server.

These models mirror the structure of the main Onyx models to avoid importing
dependencies from the main Onyx codebase. This allows the MCP server to be
run as a completely standalone service.

IMPORTANT: These models and enums must stay in sync with their source counterparts.
See backend/tests/unit/mcp_server/test_model_sync.py for validation tests.

Source locations:
- DocumentSource: onyx.configs.constants.DocumentSource
- SearchType: onyx.context.search.enums.SearchType
- LLMEvaluationType: onyx.context.search.enums.LLMEvaluationType
- IndexFilters: onyx.context.search.models.IndexFilters
- RetrievalDetails: onyx.context.search.models.RetrievalDetails
- DocumentSearchRequest: onyx.server.query_and_chat.models.DocumentSearchRequest
"""

from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel


# Enums


class DocumentSource(str, Enum):
    """Lightweight copy of onyx.configs.constants.DocumentSource

    Document source types for filtering search results.
    """

    INGESTION_API = "ingestion_api"
    SLACK = "slack"
    WEB = "web"
    GOOGLE_DRIVE = "google_drive"
    GMAIL = "gmail"
    REQUESTTRACKER = "requesttracker"
    GITHUB = "github"
    GITBOOK = "gitbook"
    GITLAB = "gitlab"
    GURU = "guru"
    BOOKSTACK = "bookstack"
    OUTLINE = "outline"
    CONFLUENCE = "confluence"
    JIRA = "jira"
    SLAB = "slab"
    PRODUCTBOARD = "productboard"
    FILE = "file"
    NOTION = "notion"
    ZULIP = "zulip"
    LINEAR = "linear"
    HUBSPOT = "hubspot"
    DOCUMENT360 = "document360"
    GONG = "gong"
    GOOGLE_SITES = "google_sites"
    ZENDESK = "zendesk"
    LOOPIO = "loopio"
    DROPBOX = "dropbox"
    SHAREPOINT = "sharepoint"
    TEAMS = "teams"
    SALESFORCE = "salesforce"
    DISCOURSE = "discourse"
    AXERO = "axero"
    CLICKUP = "clickup"
    MEDIAWIKI = "mediawiki"
    WIKIPEDIA = "wikipedia"
    ASANA = "asana"
    S3 = "s3"
    R2 = "r2"
    GOOGLE_CLOUD_STORAGE = "google_cloud_storage"
    OCI_STORAGE = "oci_storage"
    XENFORO = "xenforo"
    NOT_APPLICABLE = "not_applicable"
    DISCORD = "discord"
    FRESHDESK = "freshdesk"
    FIREFLIES = "fireflies"
    EGNYTE = "egnyte"
    AIRTABLE = "airtable"
    HIGHSPOT = "highspot"
    IMAP = "imap"
    BITBUCKET = "bitbucket"
    TESTRAIL = "testrail"
    MOCK_CONNECTOR = "mock_connector"
    USER_FILE = "user_file"


class SearchType(str, Enum):
    """Lightweight copy of onyx.context.search.enums.SearchType"""

    KEYWORD = "keyword"
    SEMANTIC = "semantic"
    INTERNET = "internet"


class LLMEvaluationType(str, Enum):
    """Lightweight copy of onyx.context.search.enums.LLMEvaluationType"""

    AGENTIC = "agentic"
    BASIC = "basic"
    SKIP = "skip"
    UNSPECIFIED = "unspecified"


# Pydantic Models


class Tag(BaseModel):
    """Lightweight copy of onyx.context.search.models.Tag"""

    tag_key: str
    tag_value: str


class BaseFilters(BaseModel):
    """Lightweight copy of onyx.context.search.models.BaseFilters

    Only includes fields used by the MCP server.
    """

    source_type: list[DocumentSource] | None = None
    document_set: list[str] | None = None
    time_cutoff: datetime | None = None
    tags: list[Tag] | None = None


class UserFileFilters(BaseModel):
    """Lightweight copy of onyx.context.search.models.UserFileFilters"""

    user_file_ids: list[UUID] | None = None
    project_id: int | None = None


class IndexFilters(BaseFilters, UserFileFilters):
    """Lightweight copy of onyx.context.search.models.IndexFilters

    Only includes fields used by the MCP server for document search requests.
    The full IndexFilters has additional fields for KG search that aren't needed here.
    """

    access_control_list: list[str] | None = None
    tenant_id: str | None = None


class ChunkContext(BaseModel):
    """Lightweight copy of onyx.context.search.models.ChunkContext"""

    chunks_above: int | None = None
    chunks_below: int | None = None
    full_doc: bool = False


class RetrievalDetails(ChunkContext):
    """Lightweight copy of onyx.context.search.models.RetrievalDetails

    Only includes fields used by the MCP server.
    """

    filters: BaseFilters | None = None
    enable_auto_detect_filters: bool | None = None
    offset: int | None = None
    limit: int | None = None


class DocumentSearchRequest(ChunkContext):
    """Lightweight copy of onyx.server.query_and_chat.models.DocumentSearchRequest

    Only includes fields used by the MCP server for the document search endpoint.
    """

    message: str
    search_type: SearchType
    retrieval_options: RetrievalDetails
    recency_bias_multiplier: float = 1.0
    evaluation_type: LLMEvaluationType
