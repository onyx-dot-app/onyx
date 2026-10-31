"""A manual Re-run Checks replaces a stored run that has been running for more
than a few minutes, so a run a worker restart left behind does not block
re-runs for hours. A run younger than that still blocks it, and system triggers
keep the long staleness bound."""

from collections.abc import Generator
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest
from sqlalchemy.orm import Session

from onyx.configs.constants import DocumentSource
from onyx.db.credential_capability import (
    get_capability_report_row,
    mark_capability_report_running,
)
from onyx.db.enums import CapabilityCheckTrigger
from onyx.db.models import ConnectorCredentialPair
from onyx.server.documents import capability_check_runs
from onyx.server.documents.capability_check_runs import start_capability_check_run
from tests.external_dependency_unit.indexing_helpers import (
    cleanup_cc_pair,
    make_cc_pair,
)


@pytest.fixture
def cc_pair(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> Generator[ConnectorCredentialPair, None, None]:
    pair = make_cc_pair(db_session, source=DocumentSource.SLACK)
    yield pair
    db_session.rollback()
    cleanup_cc_pair(db_session, pair)


def _running_since(
    db_session: Session, pair: ConnectorCredentialPair, age: timedelta
) -> None:
    row = mark_capability_report_running(
        db_session,
        credential_id=pair.credential_id,
        connector_id=None,
        source=DocumentSource.SLACK,
        trigger=CapabilityCheckTrigger.MANUAL,
        active_within=timedelta(hours=1),
    )
    assert row is not None
    row.run_started_at = datetime.now(timezone.utc) - age
    db_session.commit()


@pytest.mark.parametrize(
    ("trigger", "age", "replaced"),
    [
        (CapabilityCheckTrigger.MANUAL, timedelta(minutes=10), True),
        (CapabilityCheckTrigger.MANUAL, timedelta(minutes=1), False),
        (CapabilityCheckTrigger.CREDENTIAL_CREATED, timedelta(minutes=10), False),
    ],
)
def test_a_manual_rerun_replaces_a_run_older_than_a_few_minutes(
    db_session: Session,
    cc_pair: ConnectorCredentialPair,
    monkeypatch: pytest.MonkeyPatch,
    trigger: CapabilityCheckTrigger,
    age: timedelta,
    replaced: bool,
) -> None:
    _running_since(db_session, cc_pair, age)
    previous = get_capability_report_row(db_session, cc_pair.credential_id, None)
    assert previous is not None
    previous_run_id = previous.run_id
    send = MagicMock()
    monkeypatch.setattr(capability_check_runs, "send_capability_check_run_task", send)

    row = start_capability_check_run(
        db_session,
        user=None,
        credential_id=cc_pair.credential_id,
        connector_id=None,
        source=DocumentSource.SLACK,
        trigger=trigger,
    )

    if replaced:
        assert row is not None
        assert row.run_id != previous_run_id
        send.assert_called_once()
    else:
        assert row is None
        send.assert_not_called()
