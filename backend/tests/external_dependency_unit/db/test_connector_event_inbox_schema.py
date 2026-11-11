"""What the inbox's enum columns actually store.

A non-native `Enum` column stores the member name, so a server default or an
index predicate written in lowercase silently disagrees with every row the
ORM writes. `compare_metadata` does not catch it: both sides are VARCHAR.
"""

from collections.abc import Generator

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from onyx.configs.constants import DocumentSource
from onyx.connectors.models import InputType
from onyx.db.enums import (
    AccessType,
    ConnectorCredentialPairStatus,
    ConnectorEventStatus,
    ConnectorEventType,
)
from onyx.db.models import (
    Connector,
    ConnectorCredentialPair,
    ConnectorEventInbox,
    Credential,
)

SOURCE = DocumentSource.MOCK_CONNECTOR


@pytest.fixture
def cc_pair_id(db_session: Session) -> Generator[int, None, None]:
    connector = Connector(
        name="inbox-schema-test",
        source=SOURCE,
        input_type=InputType.POLL,
        connector_specific_config={},
    )
    credential = Credential(credential_json={}, source=SOURCE, admin_public=True)
    db_session.add_all([connector, credential])
    db_session.flush()
    pair = ConnectorCredentialPair(
        connector_id=connector.id,
        credential_id=credential.id,
        name=f"inbox-schema-pair-{connector.id}",
        status=ConnectorCredentialPairStatus.ACTIVE,
        access_type=AccessType.PUBLIC,
        total_docs_indexed=0,
    )
    db_session.add(pair)
    db_session.commit()
    try:
        yield pair.id
    finally:
        # A failed test leaves the session unusable, and the deletes below
        # would then raise and mask it.
        db_session.rollback()
        db_session.delete(pair)
        db_session.delete(connector)
        db_session.delete(credential)
        db_session.commit()


def _add_row(db_session: Session, cc_pair_id: int, event_key: str) -> None:
    db_session.add(
        ConnectorEventInbox(
            connector_credential_pair_id=cc_pair_id,
            source=SOURCE,
            document_id="doc-1",
            event_type=ConnectorEventType.UPSERT,
            event_key=event_key,
        )
    )
    db_session.commit()


def test_a_pending_row_is_covered_by_the_claim_index(
    db_session: Session, cc_pair_id: int
) -> None:
    """The partial index is `WHERE status = 'PENDING'`. A row the ORM writes
    has to match it, or the claim query silently falls back to a scan."""
    _add_row(db_session, cc_pair_id, "k-1")

    matched = db_session.execute(
        text(
            "SELECT count(*) FROM connector_event_inbox "
            "WHERE connector_credential_pair_id = :pair AND status = 'PENDING'"
        ),
        {"pair": cc_pair_id},
    ).scalar_one()
    assert matched == 1


def test_the_server_default_is_what_the_orm_reads_back(
    db_session: Session, cc_pair_id: int
) -> None:
    """A row inserted without a status takes the server default, and that
    row still has to load."""
    db_session.execute(
        text(
            "INSERT INTO connector_event_inbox "
            "(connector_credential_pair_id, source, document_id, event_type, event_key) "
            "VALUES (:pair, :source, 'doc-2', :event_type, 'k-2')"
        ),
        {
            "pair": cc_pair_id,
            "source": SOURCE.name,
            "event_type": ConnectorEventType.UPSERT.name,
        },
    )
    db_session.commit()

    row = (
        db_session.query(ConnectorEventInbox)
        .filter_by(connector_credential_pair_id=cc_pair_id, event_key="k-2")
        .one()
    )
    assert row.status == ConnectorEventStatus.PENDING
