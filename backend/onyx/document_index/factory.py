from sqlalchemy.orm import Session

from onyx.configs.app_configs import DISABLE_VECTOR_DB
from onyx.db.models import SearchSettings
from onyx.document_index.disabled import DisabledDocumentIndex
from onyx.document_index.interfaces_new import DocumentIndex
from onyx.document_index.interfaces_new import TenantState
from onyx.document_index.opensearch.opensearch_document_index import (
    OpenSearchDocumentIndex,
)
from onyx.document_index.opensearch.opensearch_document_index import OpenSearchIndexPair
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


def get_default_document_index(
    search_settings: SearchSettings,
    secondary_search_settings: SearchSettings | None,
    db_session: Session,  # noqa: ARG001
) -> DocumentIndex:
    """Gets the default document index for retrieval.

    Returns one DocumentIndex (the primary+secondary pair, with secondary None
    when no second search settings exist). For indexing flows that need to write
    to *all* configured backends, use `get_all_document_indices`.
    """
    if DISABLE_VECTOR_DB:
        return DisabledDocumentIndex()

    return _build_opensearch_pair(search_settings, secondary_search_settings)


def get_all_document_indices(
    search_settings: SearchSettings,
    secondary_search_settings: SearchSettings | None,
) -> list[DocumentIndex]:
    """Gets every document index that should be written to."""
    if DISABLE_VECTOR_DB:
        return [DisabledDocumentIndex()]

    return [_build_opensearch_pair(search_settings, secondary_search_settings)]
