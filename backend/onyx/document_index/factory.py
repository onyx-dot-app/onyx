import httpx
from sqlalchemy.orm import Session

from onyx.configs.app_configs import DISABLE_VECTOR_DB
from onyx.configs.app_configs import ENABLE_OPENSEARCH_INDEXING_FOR_ONYX
from onyx.db.models import SearchSettings
from onyx.db.opensearch_migration import get_opensearch_retrieval_state
from onyx.document_index.disabled import DisabledDocumentIndex
from onyx.document_index.interfaces import DocumentIndex
from onyx.document_index.opensearch.opensearch_document_index import (
    OpenSearchOldDocumentIndex,
)
from onyx.document_index.vespa.index import VespaIndex
from shared_configs.configs import MULTI_TENANT


def get_default_document_index(
    search_settings: SearchSettings,
    secondary_search_settings: SearchSettings | None,
    db_session: Session,
    httpx_client: httpx.Client | None = None,
) -> DocumentIndex:
    """Gets the default document index from env vars.

    To be used for retrieval only. Indexing should be done through both indices
    until Vespa is deprecated.

    Pre-existing docstring for this function, although secondary indices are not
    currently supported:
    Primary index is the index that is used for querying/updating etc. Secondary
    index is for when both the currently used index and the upcoming index both
    need to be updated, updates are applied to both indices.
    """
    if DISABLE_VECTOR_DB:
        return DisabledDocumentIndex(
            index_name=search_settings.index_name,
            secondary_index_name=(
                secondary_search_settings.index_name
                if secondary_search_settings
                else None
            ),
        )

    secondary_index_name: str | None = None
    secondary_large_chunks_enabled: bool | None = None
    if secondary_search_settings:
        secondary_index_name = secondary_search_settings.index_name
        secondary_large_chunks_enabled = secondary_search_settings.large_chunks_enabled

    opensearch_retrieval_enabled = get_opensearch_retrieval_state(db_session)
    if opensearch_retrieval_enabled:
        return OpenSearchOldDocumentIndex(
            index_name=search_settings.index_name,
            secondary_index_name=secondary_index_name,
            large_chunks_enabled=search_settings.large_chunks_enabled,
            secondary_large_chunks_enabled=secondary_large_chunks_enabled,
            multitenant=MULTI_TENANT,
            httpx_client=httpx_client,
        )
    else:
        return VespaIndex(
            index_name=search_settings.index_name,
            secondary_index_name=secondary_index_name,
            large_chunks_enabled=search_settings.large_chunks_enabled,
            secondary_large_chunks_enabled=secondary_large_chunks_enabled,
            multitenant=MULTI_TENANT,
            httpx_client=httpx_client,
        )


def get_all_document_indices(
    search_settings: SearchSettings,
    secondary_search_settings: SearchSettings | None,
    httpx_client: httpx.Client | None = None,
) -> list[DocumentIndex]:
    """Gets all document indices.

    NOTE: Will only return an OpenSearch index interface if
    ENABLE_OPENSEARCH_INDEXING_FOR_ONYX is True. This is so we don't break flows
    where we know it won't be enabled.

    Used for indexing only. Until Vespa is deprecated we will index into both
    document indices. Retrieval is done through only one index however.

    Large chunks and secondary indices are not currently supported so we
    hardcode appropriate values.

    NOTE: Make sure the Vespa index object is returned first. In the rare event
    that there is some conflict between indexing and the migration task, it is
    assumed that the state of Vespa is more up-to-date than the state of
    OpenSearch.
    """
    if DISABLE_VECTOR_DB:
        return [
            DisabledDocumentIndex(
                index_name=search_settings.index_name,
                secondary_index_name=(
                    secondary_search_settings.index_name
                    if secondary_search_settings
                    else None
                ),
            )
        ]

    vespa_document_index = VespaIndex(
        index_name=search_settings.index_name,
        secondary_index_name=(
            secondary_search_settings.index_name if secondary_search_settings else None
        ),
        large_chunks_enabled=search_settings.large_chunks_enabled,
        secondary_large_chunks_enabled=(
            secondary_search_settings.large_chunks_enabled
            if secondary_search_settings
            else None
        ),
        multitenant=MULTI_TENANT,
        httpx_client=httpx_client,
    )
    opensearch_document_index: OpenSearchOldDocumentIndex | None = None
    if ENABLE_OPENSEARCH_INDEXING_FOR_ONYX:
        opensearch_document_index = OpenSearchOldDocumentIndex(
            index_name=search_settings.index_name,
            secondary_index_name=None,
            large_chunks_enabled=False,
            secondary_large_chunks_enabled=None,
            multitenant=MULTI_TENANT,
            httpx_client=httpx_client,
        )
    result: list[DocumentIndex] = [vespa_document_index]
    if opensearch_document_index:
        result.append(opensearch_document_index)
    return result
