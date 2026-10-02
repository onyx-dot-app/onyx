"""A connector whose credential link failed validation stays behind unpaired,
by design of the link endpoint. Creating one with the same name must take that
name over, and must still refuse a name a working connector holds."""

from collections.abc import Generator
from uuid import uuid4

import pytest
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from onyx.configs.constants import DocumentSource
from onyx.connectors.models import InputType
from onyx.db.connector import create_connector
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import AccessType, ConnectorCredentialPairStatus
from onyx.db.models import Connector, ConnectorCredentialPair, Credential
from onyx.server.documents.models import ConnectorBase
from onyx.utils.threadpool_concurrency import run_functions_tuples_in_parallel


def _connector_data(name: str, source: DocumentSource) -> ConnectorBase:
    return ConnectorBase(
        name=name,
        source=source,
        input_type=InputType.LOAD_STATE,
        connector_specific_config={},
        refresh_freq=None,
        prune_freq=None,
        indexing_start=None,
    )


def _ids_named(db_session: Session, name: str) -> list[int]:
    return list(db_session.scalars(select(Connector.id).where(Connector.name == name)))


@pytest.fixture
def name(db_session: Session) -> Generator[str, None, None]:
    """A fresh connector name, with every row created under it removed after."""
    connector_name = f"failed-link-{uuid4().hex[:8]}"
    yield connector_name
    db_session.rollback()
    connector_ids = _ids_named(db_session, connector_name)
    credential_ids = list(
        db_session.scalars(
            select(ConnectorCredentialPair.credential_id).where(
                ConnectorCredentialPair.connector_id.in_(connector_ids)
            )
        )
    )
    db_session.execute(
        delete(ConnectorCredentialPair).where(
            ConnectorCredentialPair.connector_id.in_(connector_ids)
        )
    )
    db_session.execute(delete(Connector).where(Connector.id.in_(connector_ids)))
    db_session.execute(delete(Credential).where(Credential.id.in_(credential_ids)))
    db_session.commit()


def test_create_replaces_an_unpaired_connector_of_the_same_name(
    db_session: Session, name: str
) -> None:
    orphan_id = create_connector(
        db_session, _connector_data(name, DocumentSource.MOCK_CONNECTOR)
    ).id

    retry_id = create_connector(
        db_session, _connector_data(name, DocumentSource.MOCK_CONNECTOR)
    ).id

    assert retry_id != orphan_id
    assert _ids_named(db_session, name) == [retry_id]


def test_create_still_refuses_the_name_of_a_paired_connector(
    db_session: Session, name: str
) -> None:
    paired_id = create_connector(
        db_session, _connector_data(name, DocumentSource.MOCK_CONNECTOR)
    ).id
    credential = Credential(source=DocumentSource.MOCK_CONNECTOR, credential_json={})
    db_session.add(credential)
    db_session.flush()
    db_session.add(
        ConnectorCredentialPair(
            name=name,
            connector_id=paired_id,
            credential_id=credential.id,
            status=ConnectorCredentialPairStatus.ACTIVE,
            access_type=AccessType.PUBLIC,
        )
    )
    db_session.commit()

    with pytest.raises(ValueError, match="duplicate naming not allowed"):
        create_connector(
            db_session, _connector_data(name, DocumentSource.MOCK_CONNECTOR)
        )

    assert _ids_named(db_session, name) == [paired_id]


def test_same_name_under_another_source_is_left_alone(
    db_session: Session, name: str
) -> None:
    first_id = create_connector(
        db_session, _connector_data(name, DocumentSource.MOCK_CONNECTOR)
    ).id

    second_id = create_connector(
        db_session, _connector_data(name, DocumentSource.FILE)
    ).id

    assert sorted(_ids_named(db_session, name)) == sorted([first_id, second_id])


def test_a_paired_namesake_keeps_the_unpaired_one_too(
    db_session: Session, name: str
) -> None:
    unpaired = Connector(
        name=name,
        source=DocumentSource.MOCK_CONNECTOR,
        input_type=InputType.LOAD_STATE,
        connector_specific_config={},
    )
    paired = Connector(
        name=name,
        source=DocumentSource.MOCK_CONNECTOR,
        input_type=InputType.LOAD_STATE,
        connector_specific_config={},
    )
    credential = Credential(source=DocumentSource.MOCK_CONNECTOR, credential_json={})
    db_session.add_all([unpaired, paired, credential])
    db_session.flush()
    db_session.add(
        ConnectorCredentialPair(
            name=name,
            connector_id=paired.id,
            credential_id=credential.id,
            status=ConnectorCredentialPairStatus.ACTIVE,
            access_type=AccessType.PUBLIC,
        )
    )
    db_session.commit()
    unpaired_id, paired_id = unpaired.id, paired.id

    with pytest.raises(ValueError, match="duplicate naming not allowed"):
        create_connector(
            db_session, _connector_data(name, DocumentSource.MOCK_CONNECTOR)
        )

    assert sorted(_ids_named(db_session, name)) == sorted([unpaired_id, paired_id])


def _create_in_own_session(name: str) -> int | None:
    with get_session_with_current_tenant() as session:
        try:
            return create_connector(
                session, _connector_data(name, DocumentSource.MOCK_CONNECTOR)
            ).id
        except ValueError:
            return None


def test_concurrent_retries_leave_one_connector(db_session: Session, name: str) -> None:
    create_connector(db_session, _connector_data(name, DocumentSource.MOCK_CONNECTOR))

    run_functions_tuples_in_parallel(
        [(_create_in_own_session, (name,)) for _ in range(4)], max_workers=4
    )

    db_session.expire_all()
    assert len(_ids_named(db_session, name)) == 1
