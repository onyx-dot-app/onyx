import datetime
from uuid import UUID

from pydantic import BaseModel

from scratch.qdrant.schemas.source_type import SourceType


class QdrantChunk(BaseModel):
    id: UUID
    created_at: datetime.datetime
    document_id: UUID
    source_type: SourceType
    access_control_list: list[str]  # lets just say its a list of user emails
    content: str
