from dataclasses import dataclass
from datetime import datetime
from typing import Any

from onyx.document_index.opensearch.constants import DEFAULT_OPENSEARCH_VECTOR_DIMENSION
from onyx.document_index.opensearch.constants import EF_CONSTRUCTION
from onyx.document_index.opensearch.constants import M


# TODO(andrei): This should be a pydantic model.
@dataclass
class DocumentChunk:
    doc_id: str
    chunk_index: int
    chunk_size: int  # The max number of tokens in the chunk.

    title: str | None
    content: str
    title_vector: list[float] | None
    content_vector: list[float]
    num_tokens: int  # The actual number of tokens in the chunk.
    source_type: str
    document_sets: list[str] | None = None
    metadata: list[str] | None = None
    last_updated: datetime | None = None
    created_at: datetime | None = None
    access_control_list: list[str] | None = None
    global_boost: float = 1.0

    def get_opensearch_doc_chunk_id(self) -> str:
        return f"{self.doc_id}__{self.chunk_size}__{self.chunk_index}"

    def to_dict(self) -> dict[str, Any]:
        result = {
            "document_id": self.doc_id,
            "chunk_index": self.chunk_index,
            "chunk_size": self.chunk_size,
            "content": self.content,
            "content_vector": self.content_vector,
            "num_tokens": self.num_tokens,
            "source_type": self.source_type,
            "document_sets": self.document_sets,
            # TODO(andrei): Do we want to populate this if it is None?
            "metadata": self.metadata if self.metadata else None,
            "last_updated": (
                self.last_updated.isoformat() if self.last_updated else None
            ),
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "access_control_list": self.access_control_list,
            "global_boost": self.global_boost,
        }

        # Only include title and title_vector if title exists.
        if self.title:
            result["title"] = self.title
            result["title_vector"] = self.title_vector

        return result


class DocumentSchema:
    @staticmethod
    def get_document_schema(
        vector_dimension: int = DEFAULT_OPENSEARCH_VECTOR_DIMENSION,
    ) -> dict[str, Any]:
        """
        TODO(andrei): What?
        """
        return {
            "properties": {
                "title": {
                    "type": "text",
                    "fields": {
                        # Subfield accessed as title.keyword; used for exact
                        # matches, filtering, etc.
                        "keyword": {"type": "keyword", "ignore_above": 256}
                    },
                },
                "content": {
                    "type": "text",
                    # Store the content in the index, used for efficient
                    # retrieval using mget.
                    "store": True,
                },
                "title_vector": {
                    "type": "knn_vector",
                    "dimension": vector_dimension,
                    "method": {
                        "name": "hnsw",
                        "space_type": "cosinesimil",
                        "engine": "lucene",
                        "parameters": {"ef_construction": EF_CONSTRUCTION, "m": M},
                    },
                },
                "content_vector": {
                    "type": "knn_vector",
                    "dimension": vector_dimension,
                    "method": {
                        "name": "hnsw",
                        "space_type": "cosinesimil",
                        "engine": "lucene",
                        "parameters": {"ef_construction": EF_CONSTRUCTION, "m": M},
                    },
                },
                "num_tokens": {"type": "integer", "store": True},
                "source_type": {"type": "keyword"},
                # All these fields are nullable by default in OpenSearch, no
                # special handling needed.
                "document_sets": {"type": "keyword"},
                # Uses format: key:::value. TODO(andrei): What?
                "metadata": {"type": "keyword"},
                "last_updated": {
                    "type": "date",
                    "format": "strict_date_optional_time||epoch_millis",
                },
                "created_at": {
                    "type": "date",
                    "format": "strict_date_optional_time||epoch_millis",
                },
                "access_control_list": {"type": "keyword"},
                "global_boost": {"type": "float"},
                # OpenSearch metadata fields.
                "document_id": {"type": "keyword"},
                "chunk_index": {"type": "integer"},
                "chunk_size": {"type": "integer"},
            }
        }

    @staticmethod
    def get_index_settings() -> dict[str, Any]:
        """
        TODO(andrei): What?
        """
        return {
            "index": {
                "number_of_shards": 1,
                "number_of_replicas": 1,
                "knn": True,
                "knn.algo_param.ef_search": 200,
            }
        }

    @staticmethod
    def get_bulk_index_settings() -> dict[str, Any]:
        """
        Optimized settings for bulk indexing: disable refresh and replicas.

        TODO(andrei): What?
        """
        return {
            "index": {
                "number_of_shards": 1,
                "number_of_replicas": 0,  # No replication during bulk load.
                "refresh_interval": "-1",  # Disable auto-refresh.
                "knn": True,
                "knn.algo_param.ef_search": 200,
            }
        }
