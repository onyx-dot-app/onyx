from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field

from onyx.configs.constants import DocumentSource
from onyx.context.search.models import Tag, TimeRange


class GroupCount(BaseModel):
    group: str
    count: int


class DocumentOrder(str, Enum):
    """Orders of a document listing. Documents with no value sort last in
    either direction, and ties break on the document id."""

    UPDATED_DESC = "updated_desc"
    UPDATED_ASC = "updated_asc"
    CREATED_DESC = "created_desc"
    CREATED_ASC = "created_asc"
    TITLE_ASC = "title_asc"
    TITLE_DESC = "title_desc"

    @property
    def is_date(self) -> bool:
        return self not in (DocumentOrder.TITLE_ASC, DocumentOrder.TITLE_DESC)

    @property
    def is_descending(self) -> bool:
        return self in (
            DocumentOrder.UPDATED_DESC,
            DocumentOrder.CREATED_DESC,
            DocumentOrder.TITLE_DESC,
        )


class DocumentCursor(BaseModel):
    """The last document of a listing page: its position in the page's order.
    `sort_value` is that document's ordered column: a datetime for date orders,
    the title for title orders."""

    sort_value: datetime | str | None
    document_id: str


class DocumentScope(BaseModel):
    """The agent's search knowledge scope, as far as Postgres can apply it.

    Same semantics as the search filters (`onyx/document_index/FILTER_SEMANTICS.md`):
    a document is in the knowledge when any knowledge element matches it, and
    no knowledge element at all means every accessible document. The request
    filters are ANDed on top.
    """

    document_set_names: list[str] = Field(default_factory=list)
    attached_document_ids: list[str] = Field(default_factory=list)
    hierarchy_node_ids: list[int] = Field(default_factory=list)
    # Persona or project files are knowledge too, but they are not rows in
    # `document`, so no document query can match them.
    includes_user_files: bool = False

    # An empty list matches nothing.
    source_types: list[DocumentSource] | None = None
    updated_at_range: TimeRange | None = None
    created_at_range: TimeRange | None = None
    tags: list[Tag] | None = None

    @property
    def restricts_knowledge(self) -> bool:
        return self.includes_user_files or self.has_document_knowledge

    @property
    def has_document_knowledge(self) -> bool:
        return bool(
            self.document_set_names
            or self.attached_document_ids
            or self.hierarchy_node_ids
        )

    @property
    def is_unrestricted(self) -> bool:
        return not self.restricts_knowledge and (
            self.source_types is None
            and self.updated_at_range is None
            and self.created_at_range is None
            and not self.tags
        )

    @property
    def matches_no_documents(self) -> bool:
        return self.source_types == [] or (
            self.restricts_knowledge and not self.has_document_knowledge
        )
