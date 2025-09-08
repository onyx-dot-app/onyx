import concurrent.futures
import json
import uuid
from abc import ABC
from abc import abstractmethod
from collections.abc import Callable
from datetime import datetime
from datetime import timezone
from http import HTTPStatus

import httpx
from retry import retry

from onyx.connectors.cross_connector_utils.miscellaneous_utils import (
    get_experts_stores_representations,
)
from onyx.document_index.document_index_utils import get_uuid_from_chunk
from onyx.document_index.document_index_utils import get_uuid_from_chunk_info_old
from onyx.document_index.interfaces import MinimalDocumentIndexingInfo
from onyx.document_index.vespa.shared_utils.utils import remove_invalid_unicode_chars
from onyx.document_index.vespa.shared_utils.utils import (
    replace_invalid_doc_id_characters,
)
from onyx.document_index.vespa_constants import ACCESS_CONTROL_LIST
from onyx.document_index.vespa_constants import AGGREGATED_CHUNK_BOOST_FACTOR
from onyx.document_index.vespa_constants import BLURB
from onyx.document_index.vespa_constants import BOOST
from onyx.document_index.vespa_constants import CHUNK_CONTEXT
from onyx.document_index.vespa_constants import CHUNK_ID
from onyx.document_index.vespa_constants import CONTENT
from onyx.document_index.vespa_constants import CONTENT_SUMMARY
from onyx.document_index.vespa_constants import DOC_SUMMARY
from onyx.document_index.vespa_constants import DOC_UPDATED_AT
from onyx.document_index.vespa_constants import DOCUMENT_ID
from onyx.document_index.vespa_constants import DOCUMENT_ID_ENDPOINT
from onyx.document_index.vespa_constants import DOCUMENT_SETS
from onyx.document_index.vespa_constants import EMBEDDINGS
from onyx.document_index.vespa_constants import IMAGE_FILE_NAME
from onyx.document_index.vespa_constants import LARGE_CHUNK_REFERENCE_IDS
from onyx.document_index.vespa_constants import METADATA
from onyx.document_index.vespa_constants import METADATA_LIST
from onyx.document_index.vespa_constants import METADATA_SUFFIX
from onyx.document_index.vespa_constants import NUM_THREADS
from onyx.document_index.vespa_constants import PRIMARY_OWNERS
from onyx.document_index.vespa_constants import SECONDARY_OWNERS
from onyx.document_index.vespa_constants import SECTION_CONTINUATION
from onyx.document_index.vespa_constants import SEMANTIC_IDENTIFIER
from onyx.document_index.vespa_constants import SKIP_TITLE_EMBEDDING
from onyx.document_index.vespa_constants import SOURCE_LINKS
from onyx.document_index.vespa_constants import SOURCE_TYPE
from onyx.document_index.vespa_constants import TENANT_ID
from onyx.document_index.vespa_constants import TITLE
from onyx.document_index.vespa_constants import TITLE_EMBEDDING
from onyx.document_index.vespa_constants import USER_PROJECT
from onyx.indexing.models import DocMetadataAwareIndexChunk
from onyx.utils.logger import setup_logger


logger = setup_logger()


@retry(tries=3, delay=1, backoff=2)
def _does_doc_chunk_exist(
    doc_chunk_id: uuid.UUID, index_name: str, http_client: httpx.Client
) -> bool:
    doc_url = f"{DOCUMENT_ID_ENDPOINT.format(index_name=index_name)}/{doc_chunk_id}"
    doc_fetch_response = http_client.get(doc_url)
    if doc_fetch_response.status_code == 404:
        return False

    if doc_fetch_response.status_code != 200:
        logger.debug(f"Failed to check for document with URL {doc_url}")
        raise RuntimeError(
            f"Unexpected fetch document by ID value from Vespa: "
            f"error={doc_fetch_response.status_code} "
            f"index={index_name} "
            f"doc_chunk_id={doc_chunk_id}"
        )
    return True


def _vespa_get_updated_at_attribute(t: datetime | None) -> int | None:
    if not t:
        return None

    if t.tzinfo != timezone.utc:
        raise ValueError("Connectors must provide document update time in UTC")

    return int(t.timestamp())


def get_existing_documents_from_chunks(
    chunks: list[DocMetadataAwareIndexChunk],
    index_name: str,
    http_client: httpx.Client,
    executor: concurrent.futures.ThreadPoolExecutor | None = None,
) -> set[str]:
    external_executor = True

    if not executor:
        external_executor = False
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=NUM_THREADS)

    document_ids: set[str] = set()
    try:
        chunk_existence_future = {
            executor.submit(
                _does_doc_chunk_exist,
                get_uuid_from_chunk(chunk),
                index_name,
                http_client,
            ): chunk
            for chunk in chunks
        }
        for future in concurrent.futures.as_completed(chunk_existence_future):
            chunk = chunk_existence_future[future]
            chunk_already_existed = future.result()
            if chunk_already_existed:
                document_ids.add(chunk.source_document.id)

    finally:
        if not external_executor:
            executor.shutdown(wait=True)

    return document_ids


@retry(tries=5, delay=1, backoff=2)
def _index_vespa_chunk(
    chunk: DocMetadataAwareIndexChunk,
    index_name: str,
    http_client: httpx.Client,
    multitenant: bool,
) -> None:
    json_header = {
        "Content-Type": "application/json",
    }
    document = chunk.source_document

    # No minichunk documents in vespa, minichunk vectors are stored in the chunk itself

    vespa_chunk_id = str(get_uuid_from_chunk(chunk))

    embeddings = chunk.embeddings

    embeddings_name_vector_map = {"full_chunk": embeddings.full_embedding}

    if embeddings.mini_chunk_embeddings:
        for ind, m_c_embed in enumerate(embeddings.mini_chunk_embeddings):
            embeddings_name_vector_map[f"mini_chunk_{ind}"] = m_c_embed

    title = document.get_title_for_document_index()

    metadata_json = document.metadata
    cleaned_metadata_json: dict[str, str | list[str]] = {}
    for key, value in metadata_json.items():
        cleaned_key = remove_invalid_unicode_chars(key)
        if isinstance(value, list):
            cleaned_metadata_json[cleaned_key] = [
                remove_invalid_unicode_chars(item) for item in value
            ]
        else:
            cleaned_metadata_json[cleaned_key] = remove_invalid_unicode_chars(value)

    metadata_list = document.get_metadata_str_attributes()
    if metadata_list:
        metadata_list = [
            remove_invalid_unicode_chars(metadata) for metadata in metadata_list
        ]

    vespa_document_fields = {
        DOCUMENT_ID: document.id,
        CHUNK_ID: chunk.chunk_id,
        BLURB: remove_invalid_unicode_chars(chunk.blurb),
        TITLE: remove_invalid_unicode_chars(title) if title else None,
        SKIP_TITLE_EMBEDDING: not title,
        # For the BM25 index, the keyword suffix is used, the vector is already generated with the more
        # natural language representation of the metadata section
        CONTENT: remove_invalid_unicode_chars(
            f"{chunk.title_prefix}{chunk.doc_summary}{chunk.content}{chunk.chunk_context}{chunk.metadata_suffix_keyword}"
        ),
        # This duplication of `content` is needed for keyword highlighting
        # Note that it's not exactly the same as the actual content
        # which contains the title prefix and metadata suffix
        CONTENT_SUMMARY: remove_invalid_unicode_chars(chunk.content),
        SOURCE_TYPE: str(document.source.value),
        SOURCE_LINKS: json.dumps(chunk.source_links),
        SEMANTIC_IDENTIFIER: remove_invalid_unicode_chars(document.semantic_identifier),
        SECTION_CONTINUATION: chunk.section_continuation,
        LARGE_CHUNK_REFERENCE_IDS: chunk.large_chunk_reference_ids,
        METADATA: json.dumps(cleaned_metadata_json),
        # Save as a list for efficient extraction as an Attribute
        METADATA_LIST: metadata_list,
        METADATA_SUFFIX: remove_invalid_unicode_chars(chunk.metadata_suffix_keyword),
        CHUNK_CONTEXT: chunk.chunk_context,
        DOC_SUMMARY: chunk.doc_summary,
        EMBEDDINGS: embeddings_name_vector_map,
        TITLE_EMBEDDING: chunk.title_embedding,
        DOC_UPDATED_AT: _vespa_get_updated_at_attribute(document.doc_updated_at),
        PRIMARY_OWNERS: get_experts_stores_representations(document.primary_owners),
        SECONDARY_OWNERS: get_experts_stores_representations(document.secondary_owners),
        # the only `set` vespa has is `weightedset`, so we have to give each
        # element an arbitrary weight
        # rkuo: acl, docset and boost metadata are also updated through the metadata sync queue
        # which only calls VespaIndex.update
        ACCESS_CONTROL_LIST: {acl_entry: 1 for acl_entry in chunk.access.to_acl()},
        DOCUMENT_SETS: {document_set: 1 for document_set in chunk.document_sets},
        # still called `image_file_name` in Vespa for backwards compatibility
        IMAGE_FILE_NAME: chunk.image_file_id,
        USER_PROJECT: chunk.user_project if chunk.user_project is not None else [],
        BOOST: chunk.boost,
        AGGREGATED_CHUNK_BOOST_FACTOR: chunk.aggregated_chunk_boost_factor,
    }

    if multitenant:
        if chunk.tenant_id:
            vespa_document_fields[TENANT_ID] = chunk.tenant_id
    vespa_url = f"{DOCUMENT_ID_ENDPOINT.format(index_name=index_name)}/{vespa_chunk_id}"
    logger.debug(f'Indexing to URL "{vespa_url}"')
    res = http_client.post(
        vespa_url, headers=json_header, json={"fields": vespa_document_fields}
    )
    try:
        res.raise_for_status()
    except Exception as e:
        logger.exception(
            f"Failed to index document: '{document.id}'. Got response: '{res.text}'"
        )
        if isinstance(e, httpx.HTTPStatusError):
            if e.response.status_code == HTTPStatus.INSUFFICIENT_STORAGE:
                logger.error(
                    "NOTE: HTTP Status 507 Insufficient Storage usually means "
                    "you need to allocate more memory or disk space to the "
                    "Vespa/index container."
                )

        raise e


def batch_index_vespa_chunks(
    chunks: list[DocMetadataAwareIndexChunk],
    index_name: str,
    http_client: httpx.Client,
    multitenant: bool,
    executor: concurrent.futures.ThreadPoolExecutor | None = None,
) -> None:
    external_executor = True

    if not executor:
        external_executor = False
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=NUM_THREADS)

    try:
        chunk_index_future = {
            executor.submit(
                _index_vespa_chunk, chunk, index_name, http_client, multitenant
            ): chunk
            for chunk in chunks
        }
        for future in concurrent.futures.as_completed(chunk_index_future):
            # Will raise exception if any indexing raised an exception
            future.result()

    finally:
        if not external_executor:
            executor.shutdown(wait=True)


def clean_chunk_id_copy(
    chunk: DocMetadataAwareIndexChunk,
) -> DocMetadataAwareIndexChunk:
    clean_chunk = chunk.model_copy(
        update={
            "source_document": chunk.source_document.model_copy(
                update={
                    "id": replace_invalid_doc_id_characters(chunk.source_document.id)
                }
            )
        }
    )
    return clean_chunk


def check_for_final_chunk_existence(
    minimal_doc_info: MinimalDocumentIndexingInfo,
    start_index: int,
    index_name: str,
    http_client: httpx.Client,
) -> int:
    index = start_index
    while True:
        doc_chunk_id = get_uuid_from_chunk_info_old(
            document_id=minimal_doc_info.doc_id,
            chunk_id=index,
            large_chunk_reference_ids=[],
        )
        if not _does_doc_chunk_exist(doc_chunk_id, index_name, http_client):
            return index
        index += 1


class BaseHTTPXClientContext(ABC):
    """Abstract base class for an HTTPX client context manager."""

    @abstractmethod
    def __enter__(self) -> httpx.Client:
        pass

    @abstractmethod
    def __exit__(self, exc_type, exc_value, traceback):  # type: ignore
        pass


class GlobalHTTPXClientContext(BaseHTTPXClientContext):
    """Context manager for a global HTTPX client that does not close it."""

    def __init__(self, client: httpx.Client):
        self._client = client

    def __enter__(self) -> httpx.Client:
        return self._client  # Reuse the global client

    def __exit__(self, exc_type, exc_value, traceback):  # type: ignore
        pass  # Do nothing; don't close the global client


class TemporaryHTTPXClientContext(BaseHTTPXClientContext):
    """Context manager for a temporary HTTPX client that closes it after use."""

    def __init__(self, client_factory: Callable[[], httpx.Client]):
        self._client_factory = client_factory
        self._client: httpx.Client | None = None  # Client will be created in __enter__

    def __enter__(self) -> httpx.Client:
        self._client = self._client_factory()  # Create a new client
        return self._client

    def __exit__(self, exc_type, exc_value, traceback):  # type: ignore
        if self._client:
            self._client.close()
