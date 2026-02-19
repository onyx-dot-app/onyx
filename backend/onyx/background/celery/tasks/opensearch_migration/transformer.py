import traceback
from datetime import datetime
from datetime import timezone
from typing import Any

from onyx.configs.constants import PUBLIC_DOC_PAT
from onyx.document_index.interfaces_new import TenantState
from onyx.document_index.opensearch.schema import DocumentChunk
from onyx.document_index.vespa_constants import ACCESS_CONTROL_LIST
from onyx.document_index.vespa_constants import BLURB
from onyx.document_index.vespa_constants import BOOST
from onyx.document_index.vespa_constants import CHUNK_CONTEXT
from onyx.document_index.vespa_constants import CHUNK_ID
from onyx.document_index.vespa_constants import CONTENT
from onyx.document_index.vespa_constants import DOC_SUMMARY
from onyx.document_index.vespa_constants import DOC_UPDATED_AT
from onyx.document_index.vespa_constants import DOCUMENT_ID
from onyx.document_index.vespa_constants import DOCUMENT_SETS
from onyx.document_index.vespa_constants import EMBEDDINGS
from onyx.document_index.vespa_constants import FULL_CHUNK_EMBEDDING_KEY
from onyx.document_index.vespa_constants import HIDDEN
from onyx.document_index.vespa_constants import IMAGE_FILE_NAME
from onyx.document_index.vespa_constants import METADATA_LIST
from onyx.document_index.vespa_constants import METADATA_SUFFIX
from onyx.document_index.vespa_constants import PRIMARY_OWNERS
from onyx.document_index.vespa_constants import SECONDARY_OWNERS
from onyx.document_index.vespa_constants import SEMANTIC_IDENTIFIER
from onyx.document_index.vespa_constants import SOURCE_LINKS
from onyx.document_index.vespa_constants import SOURCE_TYPE
from onyx.document_index.vespa_constants import TENANT_ID
from onyx.document_index.vespa_constants import TITLE
from onyx.document_index.vespa_constants import TITLE_EMBEDDING
from onyx.document_index.vespa_constants import USER_PROJECT
from onyx.utils.logger import setup_logger
from shared_configs.configs import MULTI_TENANT

logger = setup_logger(__name__)


FIELDS_NEEDED_FOR_TRANSFORMATION: list[str] = [
    DOCUMENT_ID,
    CHUNK_ID,
    TITLE,
    TITLE_EMBEDDING,
    CONTENT,
    EMBEDDINGS,
    SOURCE_TYPE,
    METADATA_LIST,
    DOC_UPDATED_AT,
    HIDDEN,
    BOOST,
    SEMANTIC_IDENTIFIER,
    IMAGE_FILE_NAME,
    SOURCE_LINKS,
    BLURB,
    DOC_SUMMARY,
    CHUNK_CONTEXT,
    METADATA_SUFFIX,
    DOCUMENT_SETS,
    USER_PROJECT,
    PRIMARY_OWNERS,
    SECONDARY_OWNERS,
    ACCESS_CONTROL_LIST,
]
if MULTI_TENANT:
    FIELDS_NEEDED_FOR_TRANSFORMATION.append(TENANT_ID)


def _extract_content_vector(embeddings: Any) -> list[float]:
    """Extracts the full chunk embedding vector from Vespa's embeddings tensor.

    Vespa stores embeddings as a tensor<float>(t{},x[dim]) where 't' maps
    embedding names (like "full_chunk") to vectors. The API can return this in
    different formats:
    1. Direct list: {"full_chunk": [...]}
    2. Blocks format: {"blocks": {"full_chunk": [0.1, 0.2, ...]}}
    3. Possibly other formats.

    We only support formats 1 and 2. Any other supplied format will raise an
    error.

    Raises:
        ValueError: If the embeddings format is not supported.

    Returns:
        The full chunk content embedding vector as a list of floats.
    """
    if isinstance(embeddings, dict):
        # Handle format 1.
        full_chunk_embedding = embeddings.get(FULL_CHUNK_EMBEDDING_KEY)
        if isinstance(full_chunk_embedding, list):
            # Double check that within the list we have floats and not another
            # list or dict.
            if not full_chunk_embedding:
                raise ValueError("Full chunk embedding is empty.")
            if isinstance(full_chunk_embedding[0], float):
                return full_chunk_embedding

        # Handle format 2.
        blocks = embeddings.get("blocks")
        if isinstance(blocks, dict):
            full_chunk_embedding = blocks.get(FULL_CHUNK_EMBEDDING_KEY)
            if isinstance(full_chunk_embedding, list):
                # Double check that within the list we have floats and not another
                # list or dict.
                if not full_chunk_embedding:
                    raise ValueError("Full chunk embedding is empty.")
                if isinstance(full_chunk_embedding[0], float):
                    return full_chunk_embedding

    raise ValueError(f"Unknown embedding format: {type(embeddings)}")


def _extract_title_vector(title_embedding: Any | None) -> list[float] | None:
    """Extract the title embedding vector.

    Returns None if no title embedding exists.

    Vespa returns title_embedding as tensor<float>(x[dim]) which can be in
    formats:
    1. Direct list: [0.1, 0.2, ...]
    2. Values format: {"values": [0.1, 0.2, ...]}
    3. Possibly other formats.

    Only formats 1 and 2 are supported. Any other supplied format will raise an
    error.

    Raises:
        ValueError: If the title embedding format is not supported.

    Returns:
        The title embedding vector as a list of floats.
    """
    if title_embedding is None:
        return None

    # Handle format 1.
    if isinstance(title_embedding, list):
        # Double check that within the list we have floats and not another
        # list or dict.
        if not title_embedding:
            return None
        if isinstance(title_embedding[0], float):
            return title_embedding

    # Handle format 2.
    if isinstance(title_embedding, dict):
        # Try values format.
        values = title_embedding.get("values")
        if values is not None and isinstance(values, list):
            # Double check that within the list we have floats and not another
            # list or dict.
            if not values:
                return None
            if isinstance(values[0], float):
                return values

    raise ValueError(f"Unknown title embedding format: {type(title_embedding)}")


def _transform_vespa_document_sets_to_opensearch_document_sets(
    vespa_document_sets: dict[str, int] | None,
) -> list[str] | None:
    if not vespa_document_sets:
        return None
    return list(vespa_document_sets.keys())


def _transform_vespa_acl_to_opensearch_acl(
    vespa_acl: dict[str, int] | None,
) -> tuple[bool, list[str]]:
    if not vespa_acl:
        return False, []
    acl_list = list(vespa_acl.keys())
    is_public = PUBLIC_DOC_PAT in acl_list
    if is_public:
        acl_list.remove(PUBLIC_DOC_PAT)
    return is_public, acl_list


def transform_vespa_chunks_to_opensearch_chunks(
    vespa_chunks: list[dict[str, Any]],
    tenant_state: TenantState,
    sanitized_to_original_doc_id_mapping: dict[str, str],
) -> tuple[list[DocumentChunk], list[dict[str, Any]]]:
    result: list[DocumentChunk] = []
    errored_chunks: list[dict[str, Any]] = []
    for vespa_chunk in vespa_chunks:
        try:
            # This should exist; fail loudly if it does not.
            vespa_document_id: str = vespa_chunk[DOCUMENT_ID]
            if not vespa_document_id:
                raise ValueError("Missing document_id in Vespa chunk.")
            # Vespa doc IDs were sanitized using
            # replace_invalid_doc_id_characters. This was a poor design choice
            # and we don't want this in OpenSearch; whatever restrictions there
            # may be on indexed chunk ID should have no bearing on the chunk's
            # document ID field, even if document ID is an argument to the chunk
            # ID. Deliberately choose to use the real doc ID supplied to this
            # function.
            if vespa_document_id in sanitized_to_original_doc_id_mapping:
                logger.warning(
                    f"Migration warning: Vespa document ID {vespa_document_id} does not match the document ID supplied "
                    f"{sanitized_to_original_doc_id_mapping[vespa_document_id]}. "
                    "The Vespa ID will be discarded."
                )
            document_id = sanitized_to_original_doc_id_mapping.get(
                vespa_document_id, vespa_document_id
            )

            # This should exist; fail loudly if it does not.
            chunk_index: int = vespa_chunk[CHUNK_ID]

            title: str | None = vespa_chunk.get(TITLE)
            # WARNING: Should supply format.tensors=short-value to the Vespa
            # client in order to get a supported format for the tensors.
            title_vector: list[float] | None = _extract_title_vector(
                vespa_chunk.get(TITLE_EMBEDDING)
            )

            # This should exist; fail loudly if it does not.
            content: str = vespa_chunk[CONTENT]
            if not content:
                raise ValueError(
                    f"Missing content in Vespa chunk with document ID {vespa_document_id} and chunk index {chunk_index}."
                )
            # This should exist; fail loudly if it does not.
            # WARNING: Should supply format.tensors=short-value to the Vespa
            # client in order to get a supported format for the tensors.
            content_vector: list[float] = _extract_content_vector(
                vespa_chunk[EMBEDDINGS]
            )
            if not content_vector:
                raise ValueError(
                    f"Missing content_vector in Vespa chunk with document ID {vespa_document_id} and chunk index {chunk_index}."
                )

            # This should exist; fail loudly if it does not.
            source_type: str = vespa_chunk[SOURCE_TYPE]
            if not source_type:
                raise ValueError(
                    f"Missing source_type in Vespa chunk with document ID {vespa_document_id} and chunk index {chunk_index}."
                )

            metadata_list: list[str] | None = vespa_chunk.get(METADATA_LIST)

            _raw_doc_updated_at: int | None = vespa_chunk.get(DOC_UPDATED_AT)
            last_updated: datetime | None = (
                datetime.fromtimestamp(_raw_doc_updated_at, tz=timezone.utc)
                if _raw_doc_updated_at is not None
                else None
            )

            hidden: bool = vespa_chunk.get(HIDDEN, False)

            # This should exist; fail loudly if it does not.
            global_boost: int = vespa_chunk[BOOST]

            # This should exist; fail loudly if it does not.
            semantic_identifier: str = vespa_chunk[SEMANTIC_IDENTIFIER]
            if not semantic_identifier:
                raise ValueError(
                    f"Missing semantic_identifier in Vespa chunk with document ID {vespa_document_id} and chunk "
                    f"index {chunk_index}."
                )

            image_file_id: str | None = vespa_chunk.get(IMAGE_FILE_NAME)
            source_links: str | None = vespa_chunk.get(SOURCE_LINKS)
            blurb: str = vespa_chunk.get(BLURB, "")
            doc_summary: str = vespa_chunk.get(DOC_SUMMARY, "")
            chunk_context: str = vespa_chunk.get(CHUNK_CONTEXT, "")
            metadata_suffix: str | None = vespa_chunk.get(METADATA_SUFFIX)
            document_sets: list[str] | None = (
                _transform_vespa_document_sets_to_opensearch_document_sets(
                    vespa_chunk.get(DOCUMENT_SETS)
                )
            )
            user_projects: list[int] | None = vespa_chunk.get(USER_PROJECT)
            primary_owners: list[str] | None = vespa_chunk.get(PRIMARY_OWNERS)
            secondary_owners: list[str] | None = vespa_chunk.get(SECONDARY_OWNERS)

            is_public, acl_list = _transform_vespa_acl_to_opensearch_acl(
                vespa_chunk.get(ACCESS_CONTROL_LIST)
            )
            if not is_public and not acl_list:
                logger.warning(
                    f"Migration warning: Vespa chunk with document ID {vespa_document_id} and chunk index {chunk_index} has no "
                    "public ACL and no access control list. This does not make sense as it implies the document is never "
                    "searchable. Continuing with the migration..."
                )

            chunk_tenant_id: str | None = vespa_chunk.get(TENANT_ID)
            if MULTI_TENANT:
                if not chunk_tenant_id:
                    raise ValueError(
                        "Missing tenant_id in Vespa chunk in a multi-tenant environment."
                    )
                if chunk_tenant_id != tenant_state.tenant_id:
                    raise ValueError(
                        f"Chunk tenant_id {chunk_tenant_id} does not match expected tenant_id {tenant_state.tenant_id}"
                    )

            opensearch_chunk = DocumentChunk(
                # We deliberately choose to use the doc ID supplied to this function
                # over the Vespa doc ID.
                document_id=document_id,
                chunk_index=chunk_index,
                title=title,
                title_vector=title_vector,
                content=content,
                content_vector=content_vector,
                source_type=source_type,
                metadata_list=metadata_list,
                last_updated=last_updated,
                public=is_public,
                access_control_list=acl_list,
                hidden=hidden,
                global_boost=global_boost,
                semantic_identifier=semantic_identifier,
                image_file_id=image_file_id,
                source_links=source_links,
                blurb=blurb,
                doc_summary=doc_summary,
                chunk_context=chunk_context,
                metadata_suffix=metadata_suffix,
                document_sets=document_sets,
                user_projects=user_projects,
                primary_owners=primary_owners,
                secondary_owners=secondary_owners,
                tenant_id=tenant_state,
            )

            result.append(opensearch_chunk)
        except Exception:
            traceback.print_exc()
            logger.exception(
                f"Migration error: Error transforming Vespa chunk with document ID {vespa_chunk.get(DOCUMENT_ID)} "
                f"and chunk index {vespa_chunk.get(CHUNK_ID)} into an OpenSearch chunk. Continuing with "
                "the migration..."
            )
            errored_chunks.append(vespa_chunk)

    return result, errored_chunks
