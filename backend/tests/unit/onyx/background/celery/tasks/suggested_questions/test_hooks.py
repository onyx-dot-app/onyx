"""The pruning hook: questions about pruned documents are dropped only when
the prune removed documents."""

from unittest.mock import MagicMock, patch

import pytest

from onyx.background.celery.tasks.pruning import tasks as pruning_tasks

_FENCE_KEY = b"connectorpruning_fence_7"


# Covers a failed prune too: it may have removed some documents.
@pytest.mark.parametrize(
    "num_pruned,failed,expect_drop",
    [(3, False, True), (3, True, True), (0, False, False)],
)
def test_pruning_drops_questions_only_when_documents_were_pruned(
    num_pruned: int, failed: bool, expect_drop: bool
) -> None:
    redis_connector = MagicMock()
    redis_connector.prune.fenced = True
    redis_connector.prune.generator_complete = num_pruned
    redis_connector.prune.generator_failed = failed
    redis_connector.prune.failed_docs = 0
    r = MagicMock()
    r.exists.return_value = False

    connector_class = MagicMock(return_value=redis_connector)
    connector_class.get_id_from_fence_key.return_value = "7"

    with (
        patch.object(pruning_tasks, "RedisConnector", connector_class),
        patch.object(pruning_tasks, "mark_ccpair_as_pruned"),
        patch.object(pruning_tasks, "update_sync_record_status"),
        patch.object(pruning_tasks, "sweep_orphan_tags"),
        patch.object(pruning_tasks, "drop_orphaned_questions") as drop,
    ):
        pruning_tasks.monitor_ccpair_pruning_taskset(
            "tenant_x", _FENCE_KEY, r, MagicMock()
        )

    if expect_drop:
        drop.assert_called_once_with()
    else:
        drop.assert_not_called()
