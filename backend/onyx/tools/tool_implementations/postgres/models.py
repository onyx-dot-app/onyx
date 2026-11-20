from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel

from onyx.configs.constants import DocumentSource, MessageType
from onyx.db.enums import HierarchyNodeType
from onyx.db.postgres_tool import POSTGRES_TOOL_DEFAULT_LIMIT
from onyx.db.postgres_tool_models import DocumentOrder


class PostgresToolTable(str, Enum):
    DOCUMENT = "document"
    HIERARCHY_NODE = "hierarchy_node"
    CHAT_SESSION = "chat_session"
    CHAT_MESSAGE = "chat_message"
    SEARCH_DOC = "search_doc"


class PostgresQueryArgs(BaseModel):
    table: PostgresToolTable
    count: bool = False
    group_by: str | None = None
    limit: int = POSTGRES_TOOL_DEFAULT_LIMIT
    # A `next_cursor` token from the previous document page.
    cursor: str | None = None
    # Document listings only.
    order_by: DocumentOrder = DocumentOrder.UPDATED_DESC

    # Text and id filters hold any of several values; filters are ANDed.
    source_type: list[DocumentSource] | None = None
    title_contains: list[str] | None = None
    updated_after: datetime | None = None
    updated_before: datetime | None = None
    owned_by: list[str] | None = None
    parent_hierarchy_node_id: list[int] | None = None

    name_contains: list[str] | None = None
    parent_id: list[int] | None = None
    node_type: list[HierarchyNodeType] | None = None

    description_contains: list[str] | None = None
    created_after: datetime | None = None
    created_before: datetime | None = None

    chat_session_id: list[UUID] | None = None
    content_contains: list[str] | None = None
    message_type: MessageType | None = None
    sent_after: datetime | None = None
    sent_before: datetime | None = None

    chat_message_id: int | None = None
    cited_only: bool = True
