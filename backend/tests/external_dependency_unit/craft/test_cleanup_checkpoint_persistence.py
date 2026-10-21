from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.orm import Session

from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.models import Sandbox
from onyx.server.features.build.db.build_session import (
    update_sandbox_heartbeat as legacy_heartbeat,
)
from onyx.server.features.build.db.sandbox import (
    begin_provisioning_attempt__no_commit,
    begin_recovery_attempt__no_commit,
    record_cleanup_checkpoint__no_commit,
    sleep_running_sandbox__no_commit,
    update_sandbox_heartbeat,
)
from onyx.server.features.build.sandbox.models import SandboxCleanupCheckpoint
from tests.external_dependency_unit.craft.db_helpers import make_sandbox, make_user


@pytest.mark.parametrize(
    "transition", ["sleep", "provision", "recovery", "heartbeat", "legacy_heartbeat"]
)
def test_checkpoint_is_committed_for_other_workers_and_cleared_on_transition(
    db_session: Session, transition: str
) -> None:
    user = make_user(db_session)
    sandbox = make_sandbox(db_session, user)
    sandbox.provisioning_attempt_number = 1
    db_session.commit()
    sandbox_id = sandbox.id
    checkpoint = SandboxCleanupCheckpoint(
        provisioning_attempt_number=1,
        storage_identity="volume:created-at",
        last_heartbeat=sandbox.last_heartbeat,
    )
    assert record_cleanup_checkpoint__no_commit(db_session, sandbox_id, checkpoint)
    db_session.commit()

    with get_session_with_current_tenant() as worker:
        loaded = worker.get(Sandbox, sandbox_id)
        assert loaded is not None
        assert loaded.cleanup_checkpoint == {
            "provisioning_attempt_number": 1,
            "storage_identity": "volume:created-at",
            "last_heartbeat": None,
        }
        if transition == "sleep":
            assert sleep_running_sandbox__no_commit(worker, sandbox_id, 1)
        elif transition == "provision":
            assert begin_provisioning_attempt__no_commit(worker, loaded) == 2
        elif transition == "recovery":
            assert begin_recovery_attempt__no_commit(worker, sandbox_id, 1) == 2
        elif transition == "heartbeat":
            update_sandbox_heartbeat(worker, sandbox_id)
        else:
            legacy_heartbeat(sandbox_id, worker)
        worker.commit()

    db_session.expire_all()
    refreshed = db_session.get(Sandbox, sandbox_id)
    assert refreshed is not None
    assert refreshed.cleanup_checkpoint is None


def test_stale_attempt_cannot_record_cleanup_proof(db_session: Session) -> None:
    user = make_user(db_session)
    sandbox = make_sandbox(db_session, user)
    sandbox.provisioning_attempt_number = 2
    db_session.commit()
    assert not record_cleanup_checkpoint__no_commit(
        db_session,
        sandbox.id,
        SandboxCleanupCheckpoint(
            provisioning_attempt_number=1,
            storage_identity="old-volume",
            last_heartbeat=sandbox.last_heartbeat,
        ),
    )
    db_session.commit()
    db_session.refresh(sandbox)
    assert sandbox.cleanup_checkpoint is None


def test_intervening_heartbeat_fences_checkpoint_save(db_session: Session) -> None:
    user = make_user(db_session)
    sandbox = make_sandbox(db_session, user)
    sandbox.provisioning_attempt_number = 1
    sandbox.last_heartbeat = datetime.now(timezone.utc) - timedelta(days=1)
    db_session.commit()
    checkpoint = SandboxCleanupCheckpoint(
        provisioning_attempt_number=1,
        storage_identity="volume:created-at",
        last_heartbeat=sandbox.last_heartbeat,
    )
    with get_session_with_current_tenant() as worker:
        update_sandbox_heartbeat(worker, sandbox.id)
        worker.commit()
    assert not record_cleanup_checkpoint__no_commit(db_session, sandbox.id, checkpoint)
    db_session.commit()
    db_session.refresh(sandbox)
    assert sandbox.cleanup_checkpoint is None
