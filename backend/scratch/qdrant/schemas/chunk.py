import datetime
from uuid import UUID

from pydantic import BaseModel

from scratch.qdrant.schemas.source_type import SourceType


class QdrantChunk(BaseModel):
    id: UUID
    created_at: datetime.datetime
    document_id: str
    source_type: SourceType | None
    access_control_list: list[str] | None  # lets just say its a list of user emails
    content: str
