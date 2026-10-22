"""A stored connector-scoped run passes the pair's access type to the runner."""

from collections.abc import Generator
from unittest.mock import MagicMock

import pytest
from sqlalchemy.orm import Session

from onyx.background.celery.tasks.capability_checks import tasks as capability_tasks
from onyx.configs.constants import DocumentSource
from onyx.db.enums import AccessType
from onyx.db.models import ConnectorCredentialPair
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE
from tests.external_dependency_unit.indexing_helpers import (
    cleanup_cc_pair,
    make_cc_pair,
)


@pytest.fixture
def private_pair(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> Generator[ConnectorCredentialPair, None, None]:
    cc_pair = make_cc_pair(db_session, source=DocumentSource.SLACK)
    cc_pair.access_type = AccessType.PRIVATE
    db_session.commit()
    yield cc_pair
    cleanup_cc_pair(db_session, cc_pair)


@pytest.mark.parametrize("scoped_to_connector", [True, False])
def test_run_passes_the_pair_access_type(
    private_pair: ConnectorCredentialPair,
    monkeypatch: pytest.MonkeyPatch,
    scoped_to_connector: bool,
) -> None:
    generate = MagicMock(side_effect=RuntimeError("stop after the call"))
    monkeypatch.setattr(capability_tasks, "generate_capability_report", generate)

    capability_tasks.run_capability_checks_task.apply(
        kwargs={
            "credential_id": private_pair.credential_id,
            "connector_id": (
                private_pair.connector_id if scoped_to_connector else None
            ),
            "connector_specific_config": None,
            "tenant_id": POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE,
        }
    )

    generate.assert_called_once()
    assert generate.call_args.kwargs["access_type"] == (
        AccessType.PRIVATE if scoped_to_connector else None
    )
