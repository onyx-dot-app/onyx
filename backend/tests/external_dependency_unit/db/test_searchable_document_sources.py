"""The search tool and the UI source picker must agree on "every source".

The chat UI enables every source it is offered and sends them as an explicit
list. The search tool recognises that list as "no filter" by comparing it with
the sources it considers searchable, so the two sets have to be built the same
way. A source the picker never offers — an ingestion-API pair, a file-system
pair, a pair the user cannot read — must not count on the search side, and a
source the picker does offer — a federated connector, which owns no connector
row — must.
"""

from collections.abc import Generator

import pytest
from sqlalchemy.orm import Session

from onyx.configs.constants import DocumentSource, FederatedConnectorSource
from onyx.db.connector import INTERNAL_ONLY_SOURCES
from onyx.db.connector_credential_pair import fetch_searchable_document_sources
from onyx.db.enums import ProcessingMode
from onyx.db.models import ConnectorCredentialPair, FederatedConnector, User
from onyx.server.documents.connector import get_basic_connector_indexing_status
from onyx.server.federated.api import get_federated_connectors
from tests.external_dependency_unit.conftest import create_test_user, delete_test_user
from tests.external_dependency_unit.indexing_helpers import (
    cleanup_cc_pair,
    make_cc_pair,
)


@pytest.fixture
def workspace(db_session: Session) -> Generator[User, None, None]:
    """A user, one searchable pair, and three sources that must not be counted
    the same way: an ingestion-API pair, a file-system pair, and a federated
    connector that has no connector row at all."""
    user = create_test_user(db_session, "searchable-sources")
    pairs: list[ConnectorCredentialPair] = [
        make_cc_pair(db_session, DocumentSource.MOCK_CONNECTOR),
        make_cc_pair(db_session, DocumentSource.INGESTION_API),
        make_cc_pair(db_session, DocumentSource.GITHUB),
    ]
    pairs[2].processing_mode = ProcessingMode.FILE_SYSTEM
    federated = FederatedConnector(
        source=FederatedConnectorSource.FEDERATED_SLACK,
        credentials={},
        config={},
    )
    db_session.add(federated)
    db_session.commit()

    yield user

    db_session.delete(federated)
    for pair in pairs:
        cleanup_cc_pair(db_session, pair)
    delete_test_user(db_session, user)
    db_session.commit()


def _picker_sources(db_session: Session, user: User) -> set[DocumentSource]:
    """Every source the UI's picker offers: connector pairs plus federated."""
    connector_sources = {
        info.source
        for info in get_basic_connector_indexing_status(
            user=user, db_session=db_session
        )
    }
    federated_sources = {
        source
        for status in get_federated_connectors(db_session=db_session)
        if (source := status.source.to_non_federated_source()) is not None
    }
    return connector_sources | federated_sources


def test_searchable_sources_match_the_source_picker(
    db_session: Session, workspace: User
) -> None:
    searchable = fetch_searchable_document_sources(db_session, workspace)

    assert (
        set(searchable)
        == _picker_sources(db_session, workspace) - INTERNAL_ONLY_SOURCES
    )
    assert len(searchable) == len(set(searchable)), "sources are deduplicated"
    assert DocumentSource.MOCK_CONNECTOR in searchable
    assert DocumentSource.SLACK in searchable, "federated connectors are searchable"
    assert DocumentSource.INGESTION_API not in searchable
