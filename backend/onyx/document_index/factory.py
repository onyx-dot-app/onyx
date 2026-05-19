import httpx
from sqlalchemy.orm import Session

from onyx.configs.app_configs import DISABLE_VECTOR_DB
from onyx.configs.app_configs import ENABLE_OPENSEARCH_INDEXING_FOR_ONYX
from onyx.configs.app_configs import ONYX_DISABLE_VESPA
from onyx.db.models import SearchSettings
from onyx.db.opensearch_migration import get_opensearch_retrieval_state
from onyx.document_index.disabled import DisabledDocumentIndex
from onyx.document_index.interfaces_new import DocumentIndex
from onyx.document_index.interfaces_new import TenantState
from onyx.document_index.opensearch.opensearch_document_index import (
    OpenSearchDocumentIndex,
)
from onyx.document_index.opensearch.opensearch_document_index import OpenSearchIndexPair
from onyx.document_index.vespa.vespa_document_index import VespaDocumentIndex
from onyx.document_index.vespa.vespa_document_index import VespaIndexPair
from onyx.indexing.models import IndexingSetting
from shared_configs.configs import MULTI_TENANT
from shared_configs.contextvars import get_current_tenant_id


def _build_tenant_state() -> TenantState:
    return TenantState(tenant_id=get_current_tenant_id(), multitenant=MULTI_TENANT)


def _build_opensearch_pair(
    search_settings: SearchSettings,
    secondary_search_settings: SearchSettings | None,
) -> OpenSearchIndexPair:
    tenant_state = _build_tenant_state()
    indexing_setting = IndexingSetting.from_db_model(search_settings)
    primary = OpenSearchDocumentIndex(
        tenant_state=tenant_state,
        index_name=search_settings.index_name,
        embedding_dim=indexing_setting.final_embedding_dim,
        embedding_precision=indexing_setting.embedding_precision,
    )
    if secondary_search_settings is None:
        return OpenSearchIndexPair(primary=primary, secondary=None)
    secondary_indexing_setting = IndexingSetting.from_db_model(
        secondary_search_settings
    )
    secondary = OpenSearchDocumentIndex(
        tenant_state=tenant_state,
        index_name=secondary_search_settings.index_name,
        embedding_dim=secondary_indexing_setting.final_embedding_dim,
        embedding_precision=secondary_indexing_setting.embedding_precision,
    )
    return OpenSearchIndexPair(
        primary=primary,
        secondary=secondary,
        secondary_embedding_dim=secondary_indexing_setting.final_embedding_dim,
        secondary_embedding_precision=secondary_indexing_setting.embedding_precision,
    )


def _build_vespa_pair(
    search_settings: SearchSettings,
    secondary_search_settings: SearchSettings | None,
    httpx_client: httpx.Client | None,
) -> VespaIndexPair:
    tenant_state = _build_tenant_state()
    primary = VespaDocumentIndex(
        index_name=search_settings.index_name,
        tenant_state=tenant_state,
        large_chunks_enabled=search_settings.large_chunks_enabled,
        httpx_client=httpx_client,
    )
    if secondary_search_settings is None:
        return VespaIndexPair(
            primary=primary,
            secondary=None,
            secondary_index_name=None,
            secondary_embedding_dim=None,
            secondary_embedding_precision=None,
        )
    secondary_indexing_setting = IndexingSetting.from_db_model(
        secondary_search_settings
    )
    secondary = VespaDocumentIndex(
        index_name=secondary_search_settings.index_name,
        tenant_state=tenant_state,
        large_chunks_enabled=secondary_search_settings.large_chunks_enabled,
        httpx_client=httpx_client,
    )
    return VespaIndexPair(
        primary=primary,
        secondary=secondary,
        secondary_index_name=secondary_search_settings.index_name,
        secondary_embedding_dim=secondary_indexing_setting.final_embedding_dim,
        secondary_embedding_precision=secondary_indexing_setting.embedding_precision,
    )


def get_default_document_index(
    search_settings: SearchSettings,
    secondary_search_settings: SearchSettings | None,
    db_session: Session,
    httpx_client: httpx.Client | None = None,
) -> DocumentIndex:
    """Gets the default document index for retrieval.

    Returns one DocumentIndex (the primary+secondary pair, with secondary None
    when no second search settings exist). For indexing flows that need to write
    to *all* configured backends, use `get_all_document_indices`.
    """
    if DISABLE_VECTOR_DB:
        return DisabledDocumentIndex()

    opensearch_retrieval_enabled = get_opensearch_retrieval_state(db_session)
    if ONYX_DISABLE_VESPA and not opensearch_retrieval_enabled:
        raise ValueError(
            "Bug: ONYX_DISABLE_VESPA is set but opensearch_retrieval_enabled is not set."
        )

    if opensearch_retrieval_enabled:
        return _build_opensearch_pair(search_settings, secondary_search_settings)
    return _build_vespa_pair(search_settings, secondary_search_settings, httpx_client)


def get_all_document_indices(
    search_settings: SearchSettings,
    secondary_search_settings: SearchSettings | None,
    httpx_client: httpx.Client | None = None,
) -> list[DocumentIndex]:
    """Gets every document index that should be written to.

    NOTE: Make sure the Vespa index object is returned first. In the rare event
    that there is some conflict between indexing and the migration task, it is
    assumed that the state of Vespa is more up-to-date than the state of
    OpenSearch.
    """
    if DISABLE_VECTOR_DB:
        return [DisabledDocumentIndex()]

    if ONYX_DISABLE_VESPA and not ENABLE_OPENSEARCH_INDEXING_FOR_ONYX:
        raise ValueError(
            "Bug: ONYX_DISABLE_VESPA is set but ENABLE_OPENSEARCH_INDEXING_FOR_ONYX is not set."
        )

    result: list[DocumentIndex] = []
    if not ONYX_DISABLE_VESPA:
        result.append(
            _build_vespa_pair(search_settings, secondary_search_settings, httpx_client)
        )
    if ENABLE_OPENSEARCH_INDEXING_FOR_ONYX:
        result.append(
            _build_opensearch_pair(search_settings, secondary_search_settings)
        )
    return result
