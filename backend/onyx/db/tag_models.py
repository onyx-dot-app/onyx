from pydantic import BaseModel

from onyx.configs.constants import DocumentSource


class DocumentTagInput(BaseModel):
    document_id: str
    source: DocumentSource
    metadata: dict[str, str | list[str]]
