from datetime import datetime
from datetime import timezone
from typing import Any
from typing import Self

from pydantic import BaseModel
from pydantic import Field
from pydantic import field_serializer
from pydantic import field_validator
from pydantic import model_serializer
from pydantic import model_validator
from pydantic import SerializerFunctionWrapHandler

from onyx.document_index.interfaces_new import TenantState
from onyx.document_index.opensearch.constants import DEFAULT_MAX_CHUNK_SIZE
from onyx.document_index.opensearch.constants import EF_CONSTRUCTION
from onyx.document_index.opensearch.constants import EF_SEARCH
from onyx.document_index.opensearch.constants import M
from shared_configs.configs import MULTI_TENANT
from shared_configs.contextvars import get_current_tenant_id


TITLE_FIELD_NAME = "title"
TITLE_VECTOR_FIELD_NAME = "title_vector"
CONTENT_FIELD_NAME = "content"
CONTENT_VECTOR_FIELD_NAME = "content_vector"
SOURCE_TYPE_FIELD_NAME = "source_type"
METADATA_LIST_FIELD_NAME = "metadata_list"
LAST_UPDATED_FIELD_NAME = "last_updated"
PUBLIC_FIELD_NAME = "public"
ACCESS_CONTROL_LIST_FIELD_NAME = "access_control_list"
HIDDEN_FIELD_NAME = "hidden"
GLOBAL_BOOST_FIELD_NAME = "global_boost"
SEMANTIC_IDENTIFIER_FIELD_NAME = "semantic_identifier"
IMAGE_FILE_ID_FIELD_NAME = "image_file_id"
SOURCE_LINKS_FIELD_NAME = "source_links"
DOCUMENT_SETS_FIELD_NAME = "document_sets"
USER_PROJECTS_FIELD_NAME = "user_projects"
DOCUMENT_ID_FIELD_NAME = "document_id"
CHUNK_INDEX_FIELD_NAME = "chunk_index"
MAX_CHUNK_SIZE_FIELD_NAME = "max_chunk_size"
TENANT_ID_FIELD_NAME = "tenant_id"
BLURB_FIELD_NAME = "blurb"
DOC_SUMMARY_FIELD_NAME = "doc_summary"
CHUNK_CONTEXT_FIELD_NAME = "chunk_context"
METADATA_SUFFIX_FIELD_NAME = "metadata_suffix"
PRIMARY_OWNERS_FIELD_NAME = "primary_owners"
SECONDARY_OWNERS_FIELD_NAME = "secondary_owners"


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


def set_or_convert_timezone_to_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        # astimezone will raise if value does not have a timezone set.
        value = value.replace(tzinfo=timezone.utc)
    else:
        # Does appropriate time conversion if value was set in a different
        # timezone.
        value = value.astimezone(timezone.utc)
    return value


class DocumentChunk(BaseModel):
    """
    Represents a chunk of a document in the OpenSearch index.

    The names of these fields are based on the OpenSearch schema. Changes to the
    schema require changes here. See get_document_schema.

    WARNING: Relies on MULTI_TENANT which is global state. Also uses
    get_current_tenant_id. Generally relying on global state is bad, in this
    case we accept it because of the importance of validating tenant logic.
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

    source_type: str
    # A list of key-value pairs separated by INDEX_SEPARATOR. See
    # convert_metadata_dict_to_list_of_strings.
    metadata_list: list[str] | None = None
    # If it exists, time zone should always be UTC.
    last_updated: datetime | None = None

    public: bool
    access_control_list: list[str]
    # Defaults to False, currently gets written during update not index.
    hidden: bool = False

    global_boost: int

    semantic_identifier: str
    image_file_id: str | None = None
    # Contains a string representation of a dict which maps offset into the raw
    # chunk text to the link corresponding to that point.
    source_links: str | None = None
    blurb: str
    # doc_summary, chunk_context, and metadata_suffix are all stored simply to
    # reverse the augmentations to content. Ideally these would just be start
    # and stop indices into the content string. For legacy reasons they are not
    # right now.
    doc_summary: str
    chunk_context: str
    metadata_suffix: str | None = None

    document_sets: list[str] | None = None
    user_projects: list[int] | None = None
    primary_owners: list[str] | None = None
    secondary_owners: list[str] | None = None

    tenant_id: TenantState = Field(
        default_factory=lambda: TenantState(
            tenant_id=get_current_tenant_id(), multitenant=MULTI_TENANT
        )
    )

    @model_validator(mode="after")
    def check_title_and_title_vector_are_consistent(self) -> Self:
        # title and title_vector should both either be None or not.
        if self.title is not None and self.title_vector is None:
            raise ValueError("Bug: Title vector must not be None if title is not None.")
        if self.title_vector is not None and self.title is None:
            raise ValueError("Bug: Title must not be None if title vector is not None.")
        return self

    @model_serializer(mode="wrap")
    def serialize_model(
        self, handler: SerializerFunctionWrapHandler
    ) -> dict[str, object]:
        """Invokes pydantic's serialization logic, then excludes Nones.

        We do this because .model_dump(exclude_none=True) does not work after
        @field_serializer logic, so for some field serializers which return None
        and which we would like to exclude from the final dump, they would be
        included without this.

        Args:
            handler: Callable from pydantic which takes the instance of the
                model as an argument and performs standard serialization.

        Returns:
            The return of handler but with None items excluded.
        """
        serialized: dict[str, object] = handler(self)
        serialized_exclude_none = {k: v for k, v in serialized.items() if v is not None}
        return serialized_exclude_none

    @field_serializer("last_updated", mode="wrap")
    def serialize_datetime_fields_to_epoch_seconds(
        self, value: datetime | None, handler: SerializerFunctionWrapHandler
    ) -> int | None:
        """
        Serializes datetime fields to seconds since the Unix epoch.

        If there is no datetime, returns None.
        """
        if value is None:
            return None
        value = set_or_convert_timezone_to_utc(value)
        return int(value.timestamp())

    @field_validator("last_updated", mode="before")
    @classmethod
    def parse_epoch_seconds_to_datetime(cls, value: Any) -> datetime | None:
        """Parses seconds since the Unix epoch to a datetime object.

        If the input is None, returns None.

        The datetime returned will be in UTC.
        """
        if value is None:
            return None
        if isinstance(value, datetime):
            value = set_or_convert_timezone_to_utc(value)
            return value
        if not isinstance(value, int):
            raise ValueError(
                f"Bug: Expected an int for the last_updated property from OpenSearch, got {type(value)} instead."
            )
        return datetime.fromtimestamp(value, tz=timezone.utc)

    @field_serializer("tenant_id", mode="wrap")
    def serialize_tenant_state(
        self, value: TenantState, handler: SerializerFunctionWrapHandler
    ) -> str | None:
        """
        Serializes tenant_state to the tenant str if multitenant, or None if
        not.

        The idea is that in single tenant mode, the schema does not have a
        tenant_id field, so we don't want to supply it in our serialized
        DocumentChunk. This assumes the final serialized model excludes None
        fields, which serialize_model should enforce.
        """
        if not value.multitenant:
            return None
        else:
            return value.tenant_id

    @field_validator("tenant_id", mode="before")
    @classmethod
    def parse_tenant_id(cls, value: Any) -> TenantState:
        """
        Generates a TenantState from OpenSearch's tenant_id if it exists, or
        generates a default state if it does not (implies we are in single
        tenant mode).
        """
        if value is None:
            if MULTI_TENANT:
                raise ValueError(
                    "Bug: No tenant_id was supplied but multi-tenant mode is enabled."
                )
            return TenantState(
                tenant_id=get_current_tenant_id(), multitenant=MULTI_TENANT
            )
        elif isinstance(value, TenantState):
            if MULTI_TENANT != value.multitenant:
                raise ValueError(
                    f"Bug: An existing TenantState object was supplied to the DocumentChunk model but its multi-tenant mode "
                    f"({value.multitenant}) does not match the program's current global tenancy state."
                )
            return value
        elif not isinstance(value, str):
            raise ValueError(
                f"Bug: Expected a str for the tenant_id property from OpenSearch, got {type(value)} instead."
            )
        else:
            if not MULTI_TENANT:
                raise ValueError(
                    "Bug: Got a non-null str for the tenant_id property from OpenSearch but multi-tenant mode is not enabled. "
                    "This is unexpected because in single-tenant mode we don't expect to see a tenant_id."
                )
            return TenantState(tenant_id=value, multitenant=MULTI_TENANT)


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
          - "index": True fields can be queried on.
          - "doc_values": True fields can be sorted and aggregated efficiently.
            Not supported for "text" type fields.
          - "store": True fields are stored separately from the source document
            and can thus be returned from a query separately from _source.
            Generally this is not necessary.

        Args:
            vector_dimension: The dimension of vector embeddings. Must be a
                positive integer.
            multitenant: Whether the index is multitenant.

        Returns:
            A dictionary representing the document schema, to be supplied to the
                OpenSearch client. The structure of this dictionary is
                determined by OpenSearch documentation.
        """
        schema: dict[str, Any] = {
            # By default OpenSearch allows dynamically adding new properties
            # based on indexed documents. This is awful and we disable it here.
            # An exception will be raised if you try to index a new doc which
            # contains unexpected fields.
            "dynamic": "strict",
            "properties": {
                TITLE_FIELD_NAME: {
                    "type": "text",
                    "fields": {
                        # Subfield accessed as title.keyword. Not indexed for
                        # values longer than 256 chars.
                        # TODO(andrei): Ask Yuhong do we want this?
                        "keyword": {"type": "keyword", "ignore_above": 256}
                    },
                    # This makes highlighting text during queries more efficient
                    # at the cost of disk space. See
                    # https://docs.opensearch.org/latest/search-plugins/searching-data/highlight/#methods-of-obtaining-offsets
                    "index_options": "offsets",
                },
                CONTENT_FIELD_NAME: {
                    "type": "text",
                    "store": True,
                    # This makes highlighting text during queries more efficient
                    # at the cost of disk space. See
                    # https://docs.opensearch.org/latest/search-plugins/searching-data/highlight/#methods-of-obtaining-offsets
                    "index_options": "offsets",
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
                # TODO(andrei): This is a tensor in Vespa. Also look at feature
                # parity for these other method fields.
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
                SOURCE_TYPE_FIELD_NAME: {"type": "keyword"},
                METADATA_LIST_FIELD_NAME: {"type": "keyword"},
                LAST_UPDATED_FIELD_NAME: {
                    "type": "date",
                    "format": "epoch_second",
                    # For some reason date defaults to False, even though it
                    # would make sense to sort by date.
                    "doc_values": True,
                },
                # Access control fields.
                # Whether the doc is public. Could have fallen under access
                # control list but is such a broad and critical filter that it
                # is its own field. If true, ACCESS_CONTROL_LIST_FIELD_NAME
                # should have no effect on queries.
                PUBLIC_FIELD_NAME: {"type": "boolean"},
                # Access control list for the doc, excluding public access,
                # which is covered above.
                # If a user's access set contains at least one entry from this
                # set, the user should be able to retrieve this document. This
                # only applies if public is set to false; public non-hidden
                # documents are always visible to anyone in a given tenancy
                # regardless of this field.
                ACCESS_CONTROL_LIST_FIELD_NAME: {"type": "keyword"},
                # Whether the doc is hidden from search results.
                # Should clobber all other access search filters, namely
                # PUBLIC_FIELD_NAME and ACCESS_CONTROL_LIST_FIELD_NAME; up to
                # search implementations to guarantee this.
                HIDDEN_FIELD_NAME: {"type": "boolean"},
                GLOBAL_BOOST_FIELD_NAME: {"type": "integer"},
                # This field is only used for displaying a useful name for the
                # doc in the UI and is not used for searching. Disabling these
                # features to increase perf. This field is therefore essentially
                # just metadata.
                SEMANTIC_IDENTIFIER_FIELD_NAME: {
                    "type": "keyword",
                    "index": False,
                    "doc_values": False,
                    # Generally False by default; just making sure.
                    "store": False,
                },
                # Same as above; used to display an image along with the doc.
                IMAGE_FILE_ID_FIELD_NAME: {
                    "type": "keyword",
                    "index": False,
                    "doc_values": False,
                    # Generally False by default; just making sure.
                    "store": False,
                },
                # Same as above; used to link to the source doc.
                SOURCE_LINKS_FIELD_NAME: {
                    "type": "keyword",
                    "index": False,
                    "doc_values": False,
                    # Generally False by default; just making sure.
                    "store": False,
                },
                # Same as above; used to quickly summarize the doc in the UI.
                BLURB_FIELD_NAME: {
                    "type": "keyword",
                    "index": False,
                    "doc_values": False,
                    # Generally False by default; just making sure.
                    "store": False,
                },
                # Same as above.
                # TODO(andrei): If we want to search on this this needs to be
                # changed.
                DOC_SUMMARY_FIELD_NAME: {
                    "type": "keyword",
                    "index": False,
                    "doc_values": False,
                    # Generally False by default; just making sure.
                    "store": False,
                },
                # Same as above.
                # TODO(andrei): If we want to search on this this needs to be
                # changed.
                CHUNK_CONTEXT_FIELD_NAME: {
                    "type": "keyword",
                    "index": False,
                    "doc_values": False,
                    # Generally False by default; just making sure.
                    "store": False,
                },
                # Same as above.
                METADATA_SUFFIX_FIELD_NAME: {
                    "type": "keyword",
                    "index": False,
                    "doc_values": False,
                    "store": False,
                },
                # Product-specific fields.
                DOCUMENT_SETS_FIELD_NAME: {"type": "keyword"},
                USER_PROJECTS_FIELD_NAME: {"type": "integer"},
                PRIMARY_OWNERS_FIELD_NAME: {"type": "keyword"},
                SECONDARY_OWNERS_FIELD_NAME: {"type": "keyword"},
                # OpenSearch metadata fields.
                DOCUMENT_ID_FIELD_NAME: {"type": "keyword"},
                CHUNK_INDEX_FIELD_NAME: {"type": "integer"},
                # The maximum number of tokens this chunk's content can hold.
                MAX_CHUNK_SIZE_FIELD_NAME: {"type": "integer"},
            },
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
