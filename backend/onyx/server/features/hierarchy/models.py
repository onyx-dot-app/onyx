from datetime import datetime
from enum import Enum

from pydantic import BaseModel

from onyx.configs.constants import DocumentSource
from onyx.server.features.hierarchy.constants import DOCUMENT_PAGE_SIZE


class DocumentSortField(str, Enum):
    NAME = "name"
    LAST_UPDATED = "last_updated"


class DocumentSortDirection(str, Enum):
    ASC = "asc"
    DESC = "desc"


class FolderPosition(str, Enum):
    ON_TOP = "on_top"
    MIXED = "mixed"


class HierarchyNodesRequest(BaseModel):
    source: DocumentSource


class HierarchyNodeSummary(BaseModel):
    id: int
    title: str
    link: str | None
    parent_id: int | None


class HierarchyNodesResponse(BaseModel):
    nodes: list[HierarchyNodeSummary]


class DocumentPageCursor(BaseModel):
    # Fields for last_updated sorting
    last_modified: datetime | None = None
    last_synced: datetime | None = None
    # Field for name sorting
    name: str | None = None
    # Document ID for tie-breaking (always required when cursor is set)
    document_id: str

    @classmethod
    def from_document(
        cls,
        document: "DocumentSummary",
        sort_field: DocumentSortField,
    ) -> "DocumentPageCursor":
        if sort_field == DocumentSortField.NAME:
            return cls(
                name=document.title,
                document_id=document.id,
            )
        # Default: LAST_UPDATED
        return cls(
            last_modified=document.last_modified,
            last_synced=document.last_synced,
            document_id=document.id,
        )


class HierarchyNodeDocumentsRequest(BaseModel):
    parent_hierarchy_node_id: int
    cursor: DocumentPageCursor | None = None
    sort_field: DocumentSortField = DocumentSortField.LAST_UPDATED
    sort_direction: DocumentSortDirection = DocumentSortDirection.DESC
    folder_position: FolderPosition = FolderPosition.ON_TOP


class DocumentSummary(BaseModel):
    id: str
    title: str
    link: str | None
    parent_id: int | None
    last_modified: datetime | None
    last_synced: datetime | None


class HierarchyNodeDocumentsResponse(BaseModel):
    documents: list[DocumentSummary]
    next_cursor: DocumentPageCursor | None
    page_size: int = DOCUMENT_PAGE_SIZE
    sort_field: DocumentSortField = DocumentSortField.LAST_UPDATED
    sort_direction: DocumentSortDirection = DocumentSortDirection.DESC
    folder_position: FolderPosition = FolderPosition.ON_TOP
