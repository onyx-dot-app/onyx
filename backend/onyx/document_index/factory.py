from onyx.configs.app_configs import DISABLE_VECTOR_DB
from onyx.db.models import SearchSettings
from onyx.document_index.disabled import DisabledDocumentIndex
from onyx.document_index.interfaces import DocumentIndex, TenantState
from onyx.document_index.opensearch.opensearch_document_index import (
    OpenSearchDocumentIndex,
    OpenSearchIndexPair,
)
from onyx.indexing.models import IndexingSetting
from shared_configs.configs import MULTI_TENANT
from shared_configs.contextvars import get_current_tenant_id


def _build_tenant_state() -> TenantState:
    return TenantState(tenant_id=get_current_tenant_id(), multitenant=MULTI_TENANT)


def build_opensearch_document_index(
    search_settings: SearchSettings,
) -> OpenSearchDocumentIndex:
    """A single OpenSearch index handle for one search settings.

    The reindex port needs the lone index (to scan a PIT / call index_raw_chunks),
    not the primary+secondary pair `get_default_document_index` returns. Shared
    with `get_default_document_index` so the construction lives in one place.
    """
    indexing_setting = IndexingSetting.from_db_model(search_settings)
    return OpenSearchDocumentIndex(
        tenant_state=_build_tenant_state(),
        index_name=search_settings.index_name,
        embedding_dim=indexing_setting.final_embedding_dim,
        vector_quantization=indexing_setting.vector_quantization,
    )


def get_default_document_index(
    search_settings: SearchSettings,
    secondary_search_settings: SearchSettings | None,
    *,
    primary_backfill_in_progress: bool = False,
) -> DocumentIndex:
    """Gets the document index for retrieval and indexing.

    Returns the primary+secondary pair, with secondary None when no second
    search settings exist.

    ``primary_backfill_in_progress`` marks the primary as an INSTANT
    reindex-port target still backfilling (see OpenSearchIndexPair.update).
    """
    if DISABLE_VECTOR_DB:
        return DisabledDocumentIndex()

    primary = build_opensearch_document_index(search_settings)
    if secondary_search_settings is None:
        return OpenSearchIndexPair(
            primary=primary,
            secondary=None,
            primary_backfill_in_progress=primary_backfill_in_progress,
        )
    secondary_indexing_setting = IndexingSetting.from_db_model(
        secondary_search_settings
    )
    secondary = build_opensearch_document_index(secondary_search_settings)
    return OpenSearchIndexPair(
        primary=primary,
        secondary=secondary,
        secondary_embedding_dim=secondary_indexing_setting.final_embedding_dim,
        primary_backfill_in_progress=primary_backfill_in_progress,
    )
