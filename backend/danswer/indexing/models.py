from typing import TYPE_CHECKING

from pydantic import BaseModel

from danswer.access.models import DocumentAccess
from danswer.connectors.models import Document
from danswer.utils.logger import setup_logger

if TYPE_CHECKING:
    from danswer.db.models import EmbeddingModel


logger = setup_logger()


Embedding = list[float]


class ChunkEmbedding(BaseModel):
    full_embedding: Embedding
    mini_chunk_embeddings: list[Embedding]


class BaseChunk(BaseModel):
    chunk_id: int
    blurb: str  # The first sentence(s) of the first Section of the chunk
    content: str
    source_links: dict[
        int, str
    ] | None  # Holds the link and the offsets into the raw Chunk text
    section_continuation: bool  # True if this Chunk's start is not at the start of a Section


class DocAwareChunk(BaseChunk):
    # During indexing flow, we have access to a complete "Document"
    # During inference we only have access to the document id and do not reconstruct the Document
    source_document: Document

    def to_short_descriptor(self) -> str:
        """Used when logging the identity of a chunk"""
        return (
            f"Chunk ID: '{self.chunk_id}'; {self.source_document.to_short_descriptor()}"
        )


class IndexChunk(DocAwareChunk):
    embeddings: ChunkEmbedding
    title_embedding: Embedding | None


class DocMetadataAwareIndexChunk(IndexChunk):
    """An `IndexChunk` that contains all necessary metadata to be indexed. This includes
    the following:

    access: holds all information about which users should have access to the
            source document for this chunk.
    document_sets: all document sets the source document for this chunk is a part
                   of. This is used for filtering / personas.
    boost: influences the ranking of this chunk at query time. Positive -> ranked higher,
           negative -> ranked lower.
    """

    access: "DocumentAccess"
    document_sets: set[str]
    boost: int

    @classmethod
    def from_index_chunk(
        cls,
        index_chunk: IndexChunk,
        access: "DocumentAccess",
        document_sets: set[str],
        boost: int,
    ) -> "DocMetadataAwareIndexChunk":
        index_chunk_data = index_chunk.dict()
        return cls(
            **index_chunk_data,
            access=access,
            document_sets=document_sets,
            boost=boost,
        )


class EmbeddingModelDetail(BaseModel):
    model_name: str
    model_dim: int
    normalize: bool
    query_prefix: str | None
    passage_prefix: str | None

    @classmethod
    def from_model(cls, embedding_model: "EmbeddingModel") -> "EmbeddingModelDetail":
        return cls(
            model_name=embedding_model.model_name,
            model_dim=embedding_model.model_dim,
            normalize=embedding_model.normalize,
            query_prefix=embedding_model.query_prefix,
            passage_prefix=embedding_model.passage_prefix,
        )
