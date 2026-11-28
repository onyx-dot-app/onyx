"""Guards prune fan-out batching: the docs to prune are sent as one cleanup
task per document batch, each tracked in the prune taskset, carrying the prune
cc_pair and an expiry, and the generator reports the docs queued."""

from collections.abc import Generator
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.orm import Session

from onyx.configs.constants import OnyxCeleryTask
from onyx.db.models import ConnectorCredentialPair
from onyx.redis import redis_connector_prune
from onyx.redis.redis_connector import RedisConnector
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE
from tests.external_dependency_unit.indexing_helpers import (
    cleanup_cc_pair,
    make_cc_pair,
)

TENANT_ID = POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE


@pytest.fixture
def cc_pair(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> Generator[ConnectorCredentialPair, None, None]:
    pair = make_cc_pair(db_session)
    try:
        yield pair
    finally:
        RedisConnector(TENANT_ID, pair.id).prune.reset()
        cleanup_cc_pair(db_session, pair)


def test_prune_sends_one_cleanup_task_per_document_batch(
    db_session: Session, cc_pair: ConnectorCredentialPair
) -> None:
    doc_ids = {f"prune-batch-{i}" for i in range(5)}
    celery_app = MagicMock()
    redis_connector = RedisConnector(TENANT_ID, cc_pair.id)

    with patch.object(redis_connector_prune, "DOCUMENT_CLEANUP_BATCH_SIZE", 2):
        queued = redis_connector.prune.generate_tasks(
            doc_ids, celery_app, db_session, None
        )

    assert queued == len(doc_ids)
    calls = celery_app.send_task.call_args_list
    assert [len(call.kwargs["kwargs"]["document_ids"]) for call in calls] == [2, 2, 1]
    assert {
        doc_id for call in calls for doc_id in call.kwargs["kwargs"]["document_ids"]
    } == doc_ids
    for call in calls:
        assert call.args[0] == OnyxCeleryTask.DOCUMENT_BATCH_BY_CC_PAIR_CLEANUP_TASK
        assert call.kwargs["kwargs"]["prune_cc_pair_id"] == cc_pair.id
        assert call.kwargs["expires"] is not None
    assert redis_connector.prune.get_remaining() == 3
