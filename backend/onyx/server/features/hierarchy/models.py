from datetime import datetime

from pydantic import BaseModel

from onyx.configs.constants import DocumentSource
from onyx.server.features.hierarchy.constants import DOCUMENT_PAGE_SIZE


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
    last_modified: datetime | None
    last_synced: datetime | None
    document_id: str

    @classmethod
    def from_document(cls, document: "DocumentSummary") -> "DocumentPageCursor":
        return cls(
            last_modified=document.last_modified,
            last_synced=document.last_synced,
            document_id=document.id,
        )


class HierarchyNodeDocumentsRequest(BaseModel):
    parent_hierarchy_node_id: int
    cursor: DocumentPageCursor | None = None


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
