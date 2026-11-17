from collections.abc import Generator
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.orm import Session

from onyx.background.celery.tasks.pruning import tasks
from onyx.db.enums import SyncType
from onyx.db.models import ConnectorCredentialPair, SyncRecord
from onyx.db.sync_record import fail_in_progress_sync_records
from onyx.redis.redis_connector import RedisConnector
from onyx.redis.redis_pool import get_redis_client
from onyx.server.documents.cc_pair import prune_cc_pair
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
    from onyx.db.connector_edit_requests import request_prune__no_commit

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
