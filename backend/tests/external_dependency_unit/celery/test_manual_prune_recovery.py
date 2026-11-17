from collections.abc import Generator
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from onyx.background.celery.tasks.pruning import tasks
from onyx.configs.constants import DocumentSource
from onyx.db.connector_edit_requests import request_prune__no_commit
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import SyncType
from onyx.db.models import ConnectorCredentialPair, SyncRecord
from onyx.db.sync_record import fail_in_progress_sync_records
from onyx.redis.redis_connector import RedisConnector
from onyx.redis.redis_connector_prune import (
    RedisConnectorPrune,
    RedisConnectorPrunePayload,
)
from onyx.redis.redis_pool import get_redis_client
from onyx.server.documents.cc_pair import prune_cc_pair
from onyx.server.documents.connector import update_connector_files
from shared_configs.contextvars import get_current_tenant_id
from tests.external_dependency_unit.indexing_helpers import (
    cleanup_cc_pair,
    make_cc_pair,
)


@pytest.fixture
def pair(db_session: Session) -> Generator[ConnectorCredentialPair, None, None]:
    pair = make_cc_pair(db_session)
    pair.connector.prune_freq = None
    db_session.commit()
    yield pair
    RedisConnector(get_current_tenant_id(), pair.id).prune.reset()
    db_session.query(SyncRecord).filter_by(
        entity_id=pair.id, sync_type=SyncType.PRUNING
    ).delete()
    db_session.commit()
    cleanup_cc_pair(db_session, pair)


def test_manual_request_survives_lost_generator(
    db_session: Session, pair: ConnectorCredentialPair
) -> None:
    celery_app = MagicMock()
    celery_app.send_task.return_value.id = "lost-generator"
    with (
        patch(
            "onyx.server.documents.cc_pair.get_connector_credential_pair_from_id_for_user",
            return_value=pair,
        ),
        patch("onyx.server.documents.cc_pair.client_app", celery_app),
    ):
        response = prune_cc_pair(pair.id, user=MagicMock(), db_session=db_session)
    assert response.success
    db_session.refresh(pair)
    assert pair.prune_requested_at is not None
    connector = RedisConnector(get_current_tenant_id(), pair.id)
    assert connector.prune.payload is not None
    assert connector.prune.payload.prune_requested_at == pair.prune_requested_at
    get_redis_client().delete(connector.prune.active_key)
    with patch.object(tasks, "celery_find_task", return_value=False):
        tasks.validate_pruning_fence(
            get_current_tenant_id(),
            connector.prune.fence_key.encode(),
            reserved_tasks=set(),
            queued_tasks=set(),
            r=get_redis_client(),
            r_celery=MagicMock(),
        )
    assert not connector.prune.fenced
    assert tasks._is_pruning_due(pair)


def test_deferred_dispatch_returns_queued(
    db_session: Session, pair: ConnectorCredentialPair
) -> None:
    with (
        patch(
            "onyx.server.documents.cc_pair.get_connector_credential_pair_from_id_for_user",
            return_value=pair,
        ),
        patch(
            "onyx.server.documents.cc_pair.try_creating_prune_generator_task",
            return_value=None,
        ),
    ):
        response = prune_cc_pair(pair.id, user=MagicMock(), db_session=db_session)
    assert response.success
    assert response.message is not None
    assert "queued" in response.message.lower()
    db_session.refresh(pair)
    assert pair.prune_requested_at is not None


def test_request_stops_after_three_lost_attempts(
    db_session: Session, pair: ConnectorCredentialPair
) -> None:
    request_prune__no_commit(db_session, pair.id)
    db_session.commit()
    celery_app = MagicMock()
    celery_app.send_task.return_value.id = "lost-generator"
    connector = RedisConnector(get_current_tenant_id(), pair.id)
    for _ in range(3):
        assert tasks.try_creating_prune_generator_task(
            celery_app, pair, db_session, get_redis_client(), get_current_tenant_id()
        )
        fail_in_progress_sync_records(
            db_session, SyncType.PRUNING, "Lost generator", entity_id=pair.id
        )
        connector.prune.reset()
    assert (
        tasks.try_creating_prune_generator_task(
            celery_app, pair, db_session, get_redis_client(), get_current_tenant_id()
        )
        is None
    )
    db_session.refresh(pair)
    assert pair.prune_requested_at is None
    assert not tasks._is_pruning_due(pair)
    assert celery_app.send_task.call_count == 3


def test_dispatch_transaction_before_request_counts_as_an_attempt(
    db_session: Session, pair: ConnectorCredentialPair
) -> None:
    pair_id = pair.id
    db_session.rollback()
    with get_session_with_current_tenant() as dispatch_session:
        dispatch_session.execute(select(func.now()))
        request_prune__no_commit(db_session, pair_id)
        db_session.commit()
        dispatch_pair = dispatch_session.scalar(
            select(ConnectorCredentialPair).where(ConnectorCredentialPair.id == pair_id)
        )
        assert dispatch_pair is not None
        celery_app = MagicMock()
        celery_app.send_task.return_value.id = "lost-generator"
        assert tasks.try_creating_prune_generator_task(
            celery_app,
            dispatch_pair,
            dispatch_session,
            get_redis_client(),
            get_current_tenant_id(),
        )
    db_session.refresh(pair)
    record = (
        db_session.query(SyncRecord)
        .filter_by(entity_id=pair_id, sync_type=SyncType.PRUNING)
        .one()
    )
    assert pair.prune_requested_at is not None
    assert record.sync_start_time >= pair.prune_requested_at


def test_failed_sends_do_not_use_up_the_request(
    db_session: Session, pair: ConnectorCredentialPair
) -> None:
    request_prune__no_commit(db_session, pair.id)
    db_session.commit()
    broken_app = MagicMock()
    broken_app.send_task.side_effect = ConnectionError("broker down")
    connector = RedisConnector(get_current_tenant_id(), pair.id)
    for _ in range(3):
        assert (
            tasks.try_creating_prune_generator_task(
                broken_app,
                pair,
                db_session,
                get_redis_client(),
                get_current_tenant_id(),
            )
            is None
        )
        assert not connector.prune.fenced
    assert (
        db_session.query(SyncRecord)
        .filter_by(entity_id=pair.id, sync_type=SyncType.PRUNING)
        .count()
        == 0
    )
    celery_app = MagicMock()
    celery_app.send_task.return_value.id = "generator"
    assert tasks.try_creating_prune_generator_task(
        celery_app, pair, db_session, get_redis_client(), get_current_tenant_id()
    )
    assert celery_app.send_task.call_count == 1


def test_failed_index_send_keeps_prune_request_for_removed_files(
    db_session: Session, pair: ConnectorCredentialPair
) -> None:
    pair.connector.source = DocumentSource.FILE
    pair.connector.connector_specific_config = {
        "file_locations": ["gone", "keep"],
        "file_names": ["gone.txt", "keep.txt"],
    }
    db_session.commit()
    upload = MagicMock(
        file_paths=["new"], file_names=["new.txt"], zip_metadata_file_id=None
    )
    broken_app = MagicMock()
    broken_app.send_task.side_effect = ConnectionError("broker down")
    with (
        patch(
            "onyx.server.documents.connector._fetch_and_check_file_connector_cc_pair_permissions",
            return_value=pair,
        ),
        patch(
            "onyx.server.documents.connector.get_default_file_store",
            return_value=MagicMock(),
        ),
        patch("onyx.server.documents.connector.upload_files", return_value=upload),
        patch("onyx.server.documents.connector.client_app", broken_app),
    ):
        response = update_connector_files(
            pair.connector_id,
            files=[MagicMock()],
            file_ids_to_remove='["gone"]',
            user=MagicMock(),
            db_session=db_session,
        )
    assert response.file_paths == ["keep", "new"]
    db_session.refresh(pair)
    assert pair.prune_requested_at is not None
    assert tasks._is_pruning_due(pair)


def test_validator_resets_lost_generator_when_fence_writes_fail_after_send(
    db_session: Session, pair: ConnectorCredentialPair
) -> None:
    request_prune__no_commit(db_session, pair.id)
    db_session.commit()
    sent = False

    def send_task(*_args: object, **kwargs: object) -> MagicMock:
        nonlocal sent
        sent = True
        return MagicMock(id=kwargs["task_id"])

    original_set_fence = RedisConnectorPrune.set_fence

    def set_fence(
        self: RedisConnectorPrune, payload: RedisConnectorPrunePayload | None
    ) -> None:
        if sent:
            raise ConnectionError("redis down")
        original_set_fence(self, payload)

    celery_app = MagicMock()
    celery_app.send_task.side_effect = send_task
    with patch.object(RedisConnectorPrune, "set_fence", set_fence):
        tasks.try_creating_prune_generator_task(
            celery_app, pair, db_session, get_redis_client(), get_current_tenant_id()
        )
    assert celery_app.send_task.call_count == 1
    connector = RedisConnector(get_current_tenant_id(), pair.id)
    assert connector.prune.fenced
    get_redis_client().delete(connector.prune.active_key)
    with patch.object(tasks, "celery_find_task", return_value=False):
        tasks.validate_pruning_fence(
            get_current_tenant_id(),
            connector.prune.fence_key.encode(),
            reserved_tasks=set(),
            queued_tasks=set(),
            r=get_redis_client(),
            r_celery=MagicMock(),
        )
    assert not connector.prune.fenced
