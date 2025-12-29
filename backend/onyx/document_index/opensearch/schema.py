from dataclasses import dataclass
from datetime import datetime

from onyx.document_index.opensearch.constants import EF_CONSTRUCTION
from onyx.document_index.opensearch.constants import M
from onyx.document_index.opensearch.constants import VECTOR_DIMENSION


@dataclass
class DocumentChunk:
    doc_id: str
    chunk_index: int
    chunk_size: int  # the max number of tokens in the chunk

    title: str | None
    content: str
    title_vector: list[float] | None
    content_vector: list[float]
    num_tokens: int  # the actual number of tokens in the chunk
    source_type: str
    document_sets: list[str] | None = None
    metadata: list[str] | None = None
    last_updated: datetime | None = None
    created_at: datetime | None = None
    access_control_list: list[str] | None = None
    global_boost: float = 1.0

    def get_os_doc_id(self) -> str:
        return f"{self.doc_id}__{self.chunk_size}__{self.chunk_index}"

    def to_dict(self) -> dict:
        result = {
            "document_id": self.doc_id,
            "chunk_index": self.chunk_index,
            "chunk_size": self.chunk_size,
            "content": self.content,
            "content_vector": self.content_vector,
            "num_tokens": self.num_tokens,
            "source_type": self.source_type,
            "document_sets": self.document_sets,
            "metadata": self.metadata if self.metadata else None,
            "last_updated": (
                self.last_updated.isoformat() if self.last_updated else None
            ),
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "access_control_list": self.access_control_list,
            "global_boost": self.global_boost,
        }

        # Only include title and title_vector if title exists
        if self.title:
            result["title"] = self.title
            result["title_vector"] = self.title_vector

        return result


class DocumentSchema:
    @staticmethod
    def get_document_schema(vector_dimension: int = VECTOR_DIMENSION) -> dict:
        return {
            "properties": {
                "title": {
                    "type": "text",
                    "fields": {
                        # subfield accessed as title.keyword, used for exact matches, filtering, etc.
                        "keyword": {"type": "keyword", "ignore_above": 256}
                    },
                },
                "content": {
                    "type": "text",
                    # store the content in the index, used for efficient retrieval using mget
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
                # All these fields are nullable by default in OpenSearch, no special handling needed
                "document_sets": {"type": "keyword"},
                # Uses format: key:::value
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
                # OS Metadata fields
                "document_id": {"type": "keyword"},
                "chunk_index": {"type": "integer"},
                "chunk_size": {"type": "integer"},
            }
        }

    @staticmethod
    def get_index_settings() -> dict:
        return {
            "index": {
                "number_of_shards": 1,
                "number_of_replicas": 1,
                "knn": True,
                "knn.algo_param.ef_search": 200,
            }
        }

    @staticmethod
    def get_bulk_index_settings() -> dict:
        """Optimized settings for bulk indexing - disable refresh and replicas."""
        return {
            "index": {
                "number_of_shards": 1,
                "number_of_replicas": 0,  # No replication during bulk load
                "refresh_interval": "-1",  # Disable auto-refresh
                "knn": True,
                "knn.algo_param.ef_search": 200,
            }
        }
