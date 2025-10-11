from uuid import UUID

from pydantic import BaseModel
from pydantic.types import StrictFloat
from qdrant_client.models import SparseVector


class ChunkDenseEmbedding(BaseModel):
    """A chunk ID paired with its dense vector embedding."""

    chunk_id: UUID
    vector: list[StrictFloat]


class ChunkSparseEmbedding(BaseModel):
    """A chunk ID paired with its sparse vector embedding."""

    chunk_id: UUID
    vector: SparseVector
