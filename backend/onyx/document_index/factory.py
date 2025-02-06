import httpx
from sqlalchemy.orm import Session

from onyx.db.models import SearchSettings
from onyx.db.search_settings import get_current_search_settings
from onyx.document_index.interfaces import DocumentIndex
from onyx.document_index.vespa.index import VespaIndex
from shared_configs.configs import MULTI_TENANT


def get_default_document_index(
    search_settings: SearchSettings,
    secondary_search_settings: SearchSettings | None,
    httpx_client: httpx.Client | None = None,
) -> DocumentIndex:
    """Primary index is the index that is used for querying/updating etc.
    Secondary index is for when both the currently used index and the upcoming
    index both need to be updated, updates are applied to both indices"""

    secondary_index_name: str | None = None
    secondary_large_chunks_enabled: bool | None = None
    if secondary_search_settings:
        secondary_index_name = secondary_search_settings.index_name
        secondary_large_chunks_enabled = secondary_search_settings.large_chunks_enabled

    # Currently only supporting Vespa
    return VespaIndex(
        index_name=search_settings.index_name,
        secondary_index_name=secondary_index_name,
        large_chunks_enabled=search_settings.large_chunks_enabled,
        secondary_large_chunks_enabled=secondary_large_chunks_enabled,
        multitenant=MULTI_TENANT,
        httpx_client=httpx_client,
    )


def get_current_primary_default_document_index(db_session: Session) -> DocumentIndex:
    """
    TODO: Use redis to cache this or something
    """
    search_settings = get_current_search_settings(db_session)
    return get_default_document_index(
        search_settings,
        None,
    )
