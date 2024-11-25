from sqlalchemy.orm import Session

from danswer.db.search_settings import get_current_search_settings
from danswer.document_index.interfaces import DocumentIndex
from danswer.document_index.vespa.index import VespaIndex
from shared_configs.configs import MULTI_TENANT


def get_default_document_index(
    primary_index_name: str,
    secondary_index_name: str | None,
) -> DocumentIndex:
    """Primary index is the index that is used for querying/updating etc.
    Secondary index is for when both the currently used index and the upcoming
    index both need to be updated, updates are applied to both indices"""
    # Currently only supporting Vespa
    return VespaIndex(
        index_name=primary_index_name,
        secondary_index_name=secondary_index_name,
        multitenant=MULTI_TENANT,
    )


def get_current_primary_default_document_index(db_session: Session) -> DocumentIndex:
    """
    TODO: Use redis to cache this or something
    """
    search_settings = get_current_search_settings(db_session)
    return get_default_document_index(
        primary_index_name=search_settings.index_name,
        secondary_index_name=None,
    )
