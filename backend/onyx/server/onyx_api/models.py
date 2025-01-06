from pydantic import BaseModel

from onyx.connectors.models import DocumentBase


class IngestionDocument(BaseModel):
    document: DocumentBase
    cc_pair_id: int | None = None


class IngestionResult(BaseModel):
    document_id: str
    already_existed: bool


class DocMinimalInfo(BaseModel):
    document_id: str
    semantic_id: str
    link: str | None = None
