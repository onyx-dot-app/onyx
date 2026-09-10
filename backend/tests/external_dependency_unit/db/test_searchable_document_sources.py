"""The search tool and the UI source picker must agree on "every source".

The chat UI enables every source it is offered and sends them as an explicit
list. The search tool recognises that list as "no filter" by comparing it with
the sources it considers searchable, so a source the picker never offers — an
ingestion-API pair, a file-system pair, a pair the user cannot read — must not
count on the search side either.
"""

from sqlalchemy.orm import Session

from onyx.configs.constants import DocumentSource
from onyx.db.connector import INTERNAL_ONLY_SOURCES
from onyx.db.connector_credential_pair import fetch_searchable_document_sources
from onyx.db.enums import ProcessingMode
from onyx.db.models import User
from onyx.server.documents.connector import get_basic_connector_indexing_status
from tests.external_dependency_unit.conftest import create_test_user
from tests.external_dependency_unit.indexing_helpers import make_cc_pair


def _picker_sources(db_session: Session, user: User) -> set[DocumentSource]:
    """The sources `/manage/connector-status` offers — what the picker draws."""
    return {
        info.source
        for info in get_basic_connector_indexing_status(
            user=user, db_session=db_session
        )
    }


def test_searchable_sources_match_the_source_picker(db_session: Session) -> None:
    user = create_test_user(db_session, "searchable-sources")
    make_cc_pair(db_session, DocumentSource.MOCK_CONNECTOR)
    make_cc_pair(db_session, DocumentSource.INGESTION_API)
    file_system_pair = make_cc_pair(db_session, DocumentSource.GITHUB)
    file_system_pair.processing_mode = ProcessingMode.FILE_SYSTEM
    db_session.commit()

    searchable = fetch_searchable_document_sources(db_session, user)

    assert set(searchable) == _picker_sources(db_session, user) - INTERNAL_ONLY_SOURCES
    assert len(searchable) == len(set(searchable)), "sources are deduplicated"
    assert DocumentSource.MOCK_CONNECTOR in searchable
    assert DocumentSource.INGESTION_API not in searchable
