from datetime import datetime
from datetime import timezone
from typing import Any
from typing import Self

from pydantic import BaseModel
from pydantic import field_serializer
from pydantic import model_validator

from onyx.document_index.opensearch.constants import DEFAULT_MAX_CHUNK_SIZE
from onyx.document_index.opensearch.constants import EF_CONSTRUCTION
from onyx.document_index.opensearch.constants import EF_SEARCH
from onyx.document_index.opensearch.constants import M


TITLE_FIELD_NAME = "title"
TITLE_VECTOR_FIELD_NAME = "title_vector"
CONTENT_FIELD_NAME = "content"
CONTENT_VECTOR_FIELD_NAME = "content_vector"
NUM_TOKENS_FIELD_NAME = "num_tokens"
SOURCE_TYPE_FIELD_NAME = "source_type"
METADATA_FIELD_NAME = "metadata"
LAST_UPDATED_FIELD_NAME = "last_updated"
CREATED_AT_FIELD_NAME = "created_at"
PUBLIC_FIELD_NAME = "public"
ACCESS_CONTROL_LIST_FIELD_NAME = "access_control_list"
HIDDEN_FIELD_NAME = "hidden"
GLOBAL_BOOST_FIELD_NAME = "global_boost"
SEMANTIC_IDENTIFIER_FIELD_NAME = "semantic_identifier"
IMAGE_FILE_NAME_FIELD_NAME = "image_file_name"
SOURCE_LINKS_FIELD_NAME = "source_links"
DOCUMENT_SETS_FIELD_NAME = "document_sets"
PROJECT_IDS_FIELD_NAME = "project_ids"
DOCUMENT_ID_FIELD_NAME = "document_id"
CHUNK_INDEX_FIELD_NAME = "chunk_index"
MAX_CHUNK_SIZE_FIELD_NAME = "max_chunk_size"
TENANT_ID_FIELD_NAME = "tenant_id"
BLURB_FIELD_NAME = "blurb"


def get_opensearch_doc_chunk_id(
    document_id: str, chunk_index: int, max_chunk_size: int = DEFAULT_MAX_CHUNK_SIZE
) -> str:
    """
    Returns a unique identifier for the chunk.

    TODO(andrei): Add source type to this.
    TODO(andrei): Add tenant ID to this.
    TODO(andrei): Sanitize document_id in the event it contains characters that
    are not allowed in OpenSearch IDs.
    """
    return f"{document_id}__{max_chunk_size}__{chunk_index}"


class DocumentChunk(BaseModel):
    """
    Represents a chunk of a document in the OpenSearch index.

    The names of these fields are based on the OpenSearch schema. Changes to the
    schema require changes here. See get_document_schema.
    """

    model_config = {"frozen": True}

    document_id: str
    chunk_index: int
    # The maximum number of tokens this chunk's content can hold. Previously
    # there was a concept of large chunks, this is a generic concept of that. We
    # can choose to have any size of chunks in the index and they should be
    # distinct from one another.
    max_chunk_size: int = DEFAULT_MAX_CHUNK_SIZE

    # Either both should be None or both should be non-None.
    title: str | None = None
    title_vector: list[float] | None = None
    content: str
    content_vector: list[float]
    # The actual number of tokens in the chunk.
    num_tokens: int

    source_type: str
    # Application logic should store these strings the format key:::value.
    metadata: list[str] | None = None
    last_updated: datetime | None = None
    created_at: datetime | None = None

    public: bool
    access_control_list: list[str] | None = None
    # Defaults to False, currently gets written during update not index.
    hidden: bool = False

    global_boost: float = 1.0

    semantic_identifier: str
    image_file_name: str | None = None
    # Contains a string representation of a dict which maps offset into the raw
    # chunk text to the link corresponding to that point.
    source_links: str | None = None
    blurb: str

    document_sets: list[str] | None = None
    project_ids: list[int] | None = None

    tenant_id: str | None = None

    @model_validator(mode="after")
    def check_num_tokens_fits_within_max_chunk_size(self) -> Self:
        if self.num_tokens > self.max_chunk_size:
            raise ValueError(
                "Bug: Num tokens must be less than or equal to max chunk size."
            )
        return self

    @model_validator(mode="after")
    def check_title_and_title_vector_are_consistent(self) -> Self:
        # title and title_vector should both either be None or not.
        if self.title is not None and self.title_vector is None:
            raise ValueError("Bug: Title vector must not be None if title is not None.")
        if self.title_vector is not None and self.title is None:
            raise ValueError("Bug: Title must not be None if title vector is not None.")
        return self

    @field_serializer("last_updated", "created_at", mode="plain")
    def serialize_datetime_fields_to_epoch_millis(
        self, value: datetime | None
    ) -> int | None:
        """
        Serializes datetime fields to milliseconds since the Unix epoch.
        """
        if value is None:
            return None
        if value.tzinfo is None:
            # astimezone will raise if value does not have a timezone set.
            value = value.replace(tzinfo=timezone.utc)
        else:
            # Does appropriate time conversion if value was set in a different
            # timezone.
            value = value.astimezone(timezone.utc)
        # timestamp returns a float in seconds so convert to millis.
        return int(value.timestamp() * 1000)


class DocumentSchema:
    """
    Represents the schema and indexing strategies of the OpenSearch index.

    TODO(andrei): Implement multi-phase indexing strategies.
    """

    @staticmethod
    def get_document_schema(vector_dimension: int, multitenant: bool) -> dict[str, Any]:
        """Returns the document schema for the OpenSearch index.

        WARNING: Changes / additions to field names here require changes to the
        DocumentChunk class above.

        Notes:
          - By default all fields have indexing enabled.
          - By default almost all fields except text fields have doc_values
            enabled, enabling operations like sorting and aggregations.
          - By default all fields are nullable.
          - "type": "keyword" fields are stored as-is, used for exact matches,
            filtering, etc.
          - "type": "text" fields are OpenSearch-processed strings, used for
            full-text searches.
          - "store": True fields are stored and can be returned on their own,
            independent of the parent document.

        Args:
            vector_dimension: The dimension of vector embeddings. Must be a
                positive integer.
            multitenant: Whether the index is multitenant.

        Returns:
            A dictionary representing the document schema, to be supplied to the
                OpenSearch client. The structure of this dictionary is
                determined by OpenSearch documentation.
        """
        schema = {
            "properties": {
                TITLE_FIELD_NAME: {
                    "type": "text",
                    "fields": {
                        # Subfield accessed as title.keyword. Not indexed for
                        # values longer than 256 chars.
                        "keyword": {"type": "keyword", "ignore_above": 256}
                    },
                },
                CONTENT_FIELD_NAME: {
                    "type": "text",
                    "store": True,
                },
                TITLE_VECTOR_FIELD_NAME: {
                    "type": "knn_vector",
                    "dimension": vector_dimension,
                    "method": {
                        "name": "hnsw",
                        "space_type": "cosinesimil",
                        "engine": "lucene",
                        "parameters": {"ef_construction": EF_CONSTRUCTION, "m": M},
                    },
                },
                CONTENT_VECTOR_FIELD_NAME: {
                    "type": "knn_vector",
                    "dimension": vector_dimension,
                    "method": {
                        "name": "hnsw",
                        "space_type": "cosinesimil",
                        "engine": "lucene",
                        "parameters": {"ef_construction": EF_CONSTRUCTION, "m": M},
                    },
                },
                # See TODO in _convert_onyx_chunk_to_opensearch_document. I
                # don't want to actually add this to the schema until we know
                # for sure we need it. If we decide we don't I will remove this.
                # # Number of tokens in the chunk's content.
                # NUM_TOKENS_FIELD_NAME: {"type": "integer", "store": True},
                SOURCE_TYPE_FIELD_NAME: {"type": "keyword"},
                # Application logic should store in the format key:::value.
                METADATA_FIELD_NAME: {"type": "keyword"},
                LAST_UPDATED_FIELD_NAME: {
                    "type": "date",
                    "format": "epoch_millis",
                    # For some reason date defaults to False, even though it
                    # would make sense to sort by date.
                    "doc_values": True,
                },
                # See TODO in _convert_onyx_chunk_to_opensearch_document. I
                # don't want to actually add this to the schema until we know
                # for sure we need it. If we decide we don't I will remove this.
                # CREATED_AT_FIELD_NAME: {
                #     "type": "date",
                #     "format": "epoch_millis",
                #     # For some reason date defaults to False, even though it
                #     # would make sense to sort by date.
                #     "doc_values": True,
                # },
                # Access control fields.
                # Whether the doc is public. Could have fallen under access
                # control list but is such a broad and critical filter that it
                # is its own field.
                PUBLIC_FIELD_NAME: {"type": "boolean"},
                # Access control list for the doc, excluding public access,
                # which is covered above.
                ACCESS_CONTROL_LIST_FIELD_NAME: {"type": "keyword"},
                # Whether the doc is hidden from search results. Should clobber
                # all other search filters; up to search implementations to
                # guarantee this.
                HIDDEN_FIELD_NAME: {"type": "boolean"},
                GLOBAL_BOOST_FIELD_NAME: {"type": "float"},
                # This field is only used for displaying a useful name for the
                # doc in the UI and is not used for searching. Disabling these
                # features to increase perf.
                SEMANTIC_IDENTIFIER_FIELD_NAME: {
                    "type": "keyword",
                    "index": False,
                    "doc_values": False,
                    "store": False,
                },
                # Same as above; used to display an image along with the doc.
                IMAGE_FILE_NAME_FIELD_NAME: {
                    "type": "keyword",
                    "index": False,
                    "doc_values": False,
                    "store": False,
                },
                # Same as above; used to link to the source doc.
                SOURCE_LINKS_FIELD_NAME: {
                    "type": "keyword",
                    "index": False,
                    "doc_values": False,
                    "store": False,
                },
                # Same as above; used to quickly summarize the doc in the UI.
                BLURB_FIELD_NAME: {
                    "type": "keyword",
                    "index": False,
                    "doc_values": False,
                    "store": False,
                },
                # Product-specific fields.
                DOCUMENT_SETS_FIELD_NAME: {"type": "keyword"},
                PROJECT_IDS_FIELD_NAME: {"type": "integer"},
                # OpenSearch metadata fields.
                DOCUMENT_ID_FIELD_NAME: {"type": "keyword"},
                CHUNK_INDEX_FIELD_NAME: {"type": "integer"},
                # The maximum number of tokens this chunk's content can hold.
                MAX_CHUNK_SIZE_FIELD_NAME: {"type": "integer"},
            }
        }

        if multitenant:
            schema["properties"][TENANT_ID_FIELD_NAME] = {"type": "keyword"}

        return schema

    @staticmethod
    def get_index_settings() -> dict[str, Any]:
        """
        Standard settings for reasonable local index and search performance.
        """
        return {
            "index": {
                "number_of_shards": 1,
                "number_of_replicas": 1,
                # Required for vector search.
                "knn": True,
                "knn.algo_param.ef_search": EF_SEARCH,
            }
        }

    @staticmethod
    def get_bulk_index_settings() -> dict[str, Any]:
        """
        Optimized settings for bulk indexing: disable refresh and replicas.
        """
        return {
            "index": {
                "number_of_shards": 1,
                "number_of_replicas": 0,  # No replication during bulk load.
                # Disables auto-refresh, improves performance in pure indexing (no searching) scenarios.
                "refresh_interval": "-1",
                # Required for vector search.
                "knn": True,
                "knn.algo_param.ef_search": EF_SEARCH,
            }
        }
