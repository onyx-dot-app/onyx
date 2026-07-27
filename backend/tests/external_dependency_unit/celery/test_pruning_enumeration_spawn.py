"""External dependency unit tests for the spawned pruning enumeration.

Verifies the child-process enumeration harness end to end:
1. A real connector (WEB, single URL) is instantiated inside the spawned
   child from DB state, enumerated, and the result round-trips back to the
   parent through the JSON handoff file.
2. A child that fails (unreachable URL) surfaces a PruneEnumerationError in
   the parent with the child's exception text attached.

Requires Postgres + Redis (child sets prune-active liveness) + internet.
"""

from collections.abc import Generator

import pytest
from sqlalchemy.orm import Session

from onyx.background.celery.tasks.pruning.enumeration_spawn import (
    PruneEnumerationError,
    run_enumeration_in_subprocess,
)
from onyx.configs.constants import DocumentSource
from onyx.connectors.models import InputType
from onyx.db.enums import AccessType, ConnectorCredentialPairStatus
from onyx.db.models import Connector, ConnectorCredentialPair, Credential
from onyx.redis.redis_connector import RedisConnector
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA

TEST_URL = "https://example.com/"


def _create_web_cc_pair(
    db_session: Session,
    base_url: str,
) -> ConnectorCredentialPair:
    connector = Connector(
        name=f"Test enumeration-spawn Connector {base_url}",
        source=DocumentSource.WEB,
        input_type=InputType.LOAD_STATE,
        connector_specific_config={
            "base_url": base_url,
            "web_connector_type": "single",
        },
    )
    db_session.add(connector)
    db_session.flush()

    credential = Credential(
        source=DocumentSource.WEB,
        credential_json={},
        admin_public=True,
    )
    db_session.add(credential)
    db_session.flush()

    cc_pair = ConnectorCredentialPair(
        connector_id=connector.id,
        credential_id=credential.id,
        name=f"Test enumeration-spawn CC Pair {base_url}",
        status=ConnectorCredentialPairStatus.ACTIVE,
        access_type=AccessType.PUBLIC,
    )
    db_session.add(cc_pair)
    db_session.commit()
    db_session.refresh(cc_pair)
    return cc_pair


@pytest.fixture
def web_cc_pair(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> Generator[ConnectorCredentialPair, None, None]:
    cc_pair = _create_web_cc_pair(db_session, TEST_URL)
    yield cc_pair
    _cleanup(db_session, cc_pair)


@pytest.fixture
def broken_web_cc_pair(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> Generator[ConnectorCredentialPair, None, None]:
    # .invalid is a reserved TLD that can never resolve
    cc_pair = _create_web_cc_pair(db_session, "https://onyx-test.invalid/")
    yield cc_pair
    _cleanup(db_session, cc_pair)


def _cleanup(db_session: Session, cc_pair: ConnectorCredentialPair) -> None:
    connector_id = cc_pair.connector_id
    credential_id = cc_pair.credential_id
    db_session.query(ConnectorCredentialPair).filter(
        ConnectorCredentialPair.id == cc_pair.id
    ).delete()
    db_session.query(Connector).filter(Connector.id == connector_id).delete()
    db_session.query(Credential).filter(Credential.id == credential_id).delete()
    db_session.commit()


def test_spawned_enumeration_success(
    web_cc_pair: ConnectorCredentialPair,
) -> None:
    """The child enumerates a single-URL web connector and the result
    round-trips through the JSON handoff file."""
    reacquire_calls: list[int] = []

    result = run_enumeration_in_subprocess(
        cc_pair_id=web_cc_pair.id,
        connector_id=web_cc_pair.connector_id,
        credential_id=web_cc_pair.credential_id,
        tenant_id=POSTGRES_DEFAULT_SCHEMA,
        redis_connector=RedisConnector(POSTGRES_DEFAULT_SCHEMA, web_cc_pair.id),
        reacquire_lock=lambda: reacquire_calls.append(1),
    )

    # single-page crawl of example.com yields exactly that URL
    assert set(result.raw_id_to_parent.keys()) == {TEST_URL}
    assert result.raw_id_to_parent[TEST_URL] is None
    assert result.hierarchy_nodes == []


def test_spawned_enumeration_child_failure(
    broken_web_cc_pair: ConnectorCredentialPair,
) -> None:
    """A child that cannot reach its source fails the enumeration with the
    child's exception text surfaced to the parent."""
    with pytest.raises(PruneEnumerationError) as exc_info:
        run_enumeration_in_subprocess(
            cc_pair_id=broken_web_cc_pair.id,
            connector_id=broken_web_cc_pair.connector_id,
            credential_id=broken_web_cc_pair.credential_id,
            tenant_id=POSTGRES_DEFAULT_SCHEMA,
            redis_connector=RedisConnector(
                POSTGRES_DEFAULT_SCHEMA, broken_web_cc_pair.id
            ),
            reacquire_lock=lambda: None,
        )

    # the child exits nonzero and its traceback is attached
    assert "exit_code" in str(exc_info.value)
