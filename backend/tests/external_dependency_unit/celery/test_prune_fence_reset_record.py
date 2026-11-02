"""A prune whose fence is reset without finishing must end its sync record as
FAILED with the reason, so the admin UI stops showing a prune nothing runs."""

from collections.abc import Generator
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.background.celery.tasks.pruning import tasks as pruning_tasks
from onyx.configs.constants import DocumentSource
from onyx.connectors.models import InputType
from onyx.db.enums import (
    AccessType,
    ConnectorCredentialPairStatus,
    SyncStatus,
    SyncType,
)
from onyx.db.models import Connector, ConnectorCredentialPair, Credential, SyncRecord
from onyx.db.sync_record import (
    fail_in_progress_sync_records,
    insert_sync_record,
    update_sync_record_status,
)
from onyx.redis.redis_connector import RedisConnector
from onyx.redis.redis_connector_prune import RedisConnectorPrunePayload
from onyx.redis.redis_pool import get_redis_client
from shared_configs.contextvars import get_current_tenant_id

_REASON = "test: fence reset"


@pytest.fixture
def cc_pair(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> Generator[ConnectorCredentialPair, None, None]:
    connector = Connector(
        name="Prune fence reset record",
        source=DocumentSource.CONFLUENCE,
        input_type=InputType.POLL,
        connector_specific_config={},
    )
    credential = Credential(
        source=DocumentSource.CONFLUENCE, credential_json={}, admin_public=True
    )
    db_session.add_all([connector, credential])
    db_session.flush()
    pair = ConnectorCredentialPair(
        connector_id=connector.id,
        credential_id=credential.id,
        name="Prune fence reset record",
        status=ConnectorCredentialPairStatus.ACTIVE,
        access_type=AccessType.PUBLIC,
    )
    db_session.add(pair)
    db_session.commit()

    yield pair

    RedisConnector(get_current_tenant_id(), pair.id).prune.reset()
    db_session.query(SyncRecord).filter(
        SyncRecord.entity_id == pair.id, SyncRecord.sync_type == SyncType.PRUNING
    ).delete()
    db_session.delete(pair)
    db_session.flush()
    db_session.delete(connector)
    db_session.delete(credential)
    db_session.commit()


def _prune_records(db_session: Session, cc_pair_id: int) -> dict[int, SyncRecord]:
    db_session.expire_all()
    records = db_session.scalars(
        select(SyncRecord).where(
            SyncRecord.entity_id == cc_pair_id,
            SyncRecord.sync_type == SyncType.PRUNING,
        )
    ).all()
    return {record.id: record for record in records}


def test_fail_in_progress_sync_records_leaves_finished_records_alone(
    db_session: Session, cc_pair: ConnectorCredentialPair
) -> None:
    finished = insert_sync_record(db_session, cc_pair.id, SyncType.PRUNING).id
    update_sync_record_status(
        db_session, cc_pair.id, SyncType.PRUNING, SyncStatus.SUCCESS
    )
    running = insert_sync_record(db_session, cc_pair.id, SyncType.PRUNING).id

    failed_ids = fail_in_progress_sync_records(
        db_session, SyncType.PRUNING, _REASON, entity_id=cc_pair.id
    )

    assert failed_ids == [running]
    records = _prune_records(db_session, cc_pair.id)
    assert records[finished].sync_status == SyncStatus.SUCCESS
    assert records[finished].error_message is None
    assert records[running].sync_status == SyncStatus.FAILED
    assert records[running].error_message == _REASON
    assert records[running].sync_end_time is not None


def test_validator_reset_fails_the_running_prune_record(
    db_session: Session, cc_pair: ConnectorCredentialPair
) -> None:
    """A fence whose generator task is nowhere in celery and whose active
    signal expired is a crashed prune: the validator resets the fence and the
    record ends as FAILED."""
    tenant_id = get_current_tenant_id()
    redis_connector = RedisConnector(tenant_id, cc_pair.id)
    record_id = insert_sync_record(db_session, cc_pair.id, SyncType.PRUNING).id
    redis_connector.prune.set_fence(
        RedisConnectorPrunePayload(
            id="test",
            submitted=datetime.now(timezone.utc),
            started=None,
            celery_task_id=f"{redis_connector.prune.generator_task_key}_lost",
        )
    )
    assert redis_connector.prune.fenced
    assert not redis_connector.prune.active()

    with patch.object(pruning_tasks, "celery_find_task", return_value=False):
        pruning_tasks.validate_pruning_fence(
            tenant_id,
            redis_connector.prune.fence_key.encode(),
            reserved_tasks=set(),
            queued_tasks=set(),
            r=get_redis_client(tenant_id=tenant_id),
            r_celery=MagicMock(),
        )

    assert not redis_connector.prune.fenced
    record = _prune_records(db_session, cc_pair.id)[record_id]
    assert record.sync_status == SyncStatus.FAILED
    assert record.error_message == pruning_tasks.PRUNE_LOST_TASK_MSG


def test_startup_reset_holds_the_dispatch_lock_past_a_dispatch_hold(
    tenant_context: None,  # noqa: ARG001
) -> None:
    """Both steps run under the dispatch lock with a TTL longer than a
    dispatcher's, renewed between them, and the lock is free afterward. The
    steps are stubbed: the real ones touch every pair in the shared dev stores."""
    r = get_redis_client(tenant_id=get_current_tenant_id())
    lock_ttls: list[int] = []

    def _record_lock_ttl(*_args: object, **_kwargs: object) -> None:
        lock_ttls.append(r.ttl(pruning_tasks.PRUNE_DISPATCH_LOCK_NAME))

    with (
        patch.object(
            pruning_tasks, "fail_orphaned_prune_records", side_effect=_record_lock_ttl
        ),
        patch.object(
            pruning_tasks.RedisConnectorPrune,
            "reset_all",
            side_effect=_record_lock_ttl,
        ),
    ):
        pruning_tasks.reset_prune_fences_on_startup(r)

    assert len(lock_ttls) == 2
    assert all(ttl > pruning_tasks.PRUNE_DISPATCH_LOCK_TIMEOUT for ttl in lock_ttls)
    assert not r.exists(pruning_tasks.PRUNE_DISPATCH_LOCK_NAME)
