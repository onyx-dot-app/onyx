from dataclasses import dataclass
from dataclasses import fields
from datetime import datetime
from typing import TYPE_CHECKING

from pydantic import BaseModel

from danswer.access.models import DocumentAccess
from danswer.configs.constants import DocumentSource
from danswer.connectors.models import Document
from danswer.utils.logger import setup_logger

if TYPE_CHECKING:
    from danswer.db.models import EmbeddingModel


logger = setup_logger()


Embedding = list[float]


@dataclass
class ChunkEmbedding:
    full_embedding: Embedding
    mini_chunk_embeddings: list[Embedding]


@dataclass
class BaseChunk:
    chunk_id: int
    blurb: str  # The first sentence(s) of the first Section of the chunk
    content: str
    source_links: dict[
        int, str
    ] | None  # Holds the link and the offsets into the raw Chunk text
    section_continuation: bool  # True if this Chunk's start is not at the start of a Section


@dataclass
class DocAwareChunk(BaseChunk):
    # During indexing flow, we have access to a complete "Document"
    # During inference we only have access to the document id and do not reconstruct the Document
    source_document: Document

    def to_short_descriptor(self) -> str:
        """Used when logging the identity of a chunk"""
        return (
            f"Chunk ID: '{self.chunk_id}'; {self.source_document.to_short_descriptor()}"
        )


@dataclass
class IndexChunk(DocAwareChunk):
    embeddings: ChunkEmbedding
    title_embedding: Embedding | None


@dataclass
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
        return cls(
            **{
                field.name: getattr(index_chunk, field.name)
                for field in fields(index_chunk)
            },
            access=access,
            document_sets=document_sets,
            boost=boost,
        )


@dataclass
class InferenceChunk(BaseChunk):
    document_id: str
    source_type: DocumentSource
    semantic_identifier: str
    boost: int
    recency_bias: float
    score: float | None
    hidden: bool
    metadata: dict[str, str | list[str]]
    # Matched sections in the chunk. Uses Vespa syntax e.g. <hi>TEXT</hi>
    # to specify that a set of words should be highlighted. For example:
    # ["<hi>the</hi> <hi>answer</hi> is 42", "he couldn't find an <hi>answer</hi>"]
    match_highlights: list[str]
    # when the doc was last updated
    updated_at: datetime | None
    primary_owners: list[str] | None = None
    secondary_owners: list[str] | None = None

    @property
    def unique_id(self) -> str:
        return f"{self.document_id}__{self.chunk_id}"

    def __repr__(self) -> str:
        blurb_words = self.blurb.split()
        short_blurb = ""
        for word in blurb_words:
            if not short_blurb:
                short_blurb = word
                continue
            if len(short_blurb) > 25:
                break
            short_blurb += " " + word
        return f"Inference Chunk: {self.document_id} - {short_blurb}..."


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
