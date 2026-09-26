from logging import Logger
from unittest.mock import Mock, patch

import pytest
from redis.lock import Lock as RedisLock

from ee.onyx.background.celery.tasks.doc_permission_syncing.tasks import (
    DOCUMENT_PERMISSION_SYNC_BATCH_SIZE,
    _update_streamed_permissions,
)
from onyx.access.models import (
    DocExternalAccess,
    ElementExternalAccess,
    ExternalAccess,
    NodeExternalAccess,
)
from onyx.redis.redis_connector_doc_perm_sync import (
    PermissionSyncResult,
    RedisConnectorPermissionSync,
)
from onyx.redis.tenant_redis_client import TenantRedisClient


@pytest.mark.parametrize("element_kind", ["document", "node"])
@pytest.mark.parametrize("with_logger", [False, True])
def test_oversized_acl_counts_as_error_and_continues(
    element_kind: str, with_logger: bool
) -> None:
    at_limit = ExternalAccess(
        external_user_emails={"member@example.com"},
        external_user_group_ids={
            f"group-{index}" for index in range(ExternalAccess.MAX_NUM_ENTRIES - 1)
        },
        is_public=False,
    )
    oversized = ExternalAccess(
        external_user_emails=at_limit.external_user_emails,
        external_user_group_ids=at_limit.external_user_group_ids | {"extra-group"},
        is_public=False,
    )
    rejected: ElementExternalAccess = (
        DocExternalAccess(external_access=oversized, doc_id="rejected-document")
        if element_kind == "document"
        else NodeExternalAccess(
            external_access=oversized, raw_node_id="rejected-node", source="test"
        )
    )
    accepted: ElementExternalAccess = (
        DocExternalAccess(external_access=at_limit, doc_id="accepted-document")
        if element_kind == "document"
        else NodeExternalAccess(
            external_access=at_limit, raw_node_id="accepted-node", source="test"
        )
    )
    sync = RedisConnectorPermissionSync("public", 1, Mock(spec=TenantRedisClient))
    update_permissions = Mock()
    classify_documents = Mock(return_value={"accepted-document"})

    with patch(
        "onyx.redis.redis_connector_doc_perm_sync.fetch_versioned_implementation"
    ) as resolve_implementation:
        resolve_implementation.side_effect = [update_permissions, classify_documents]
        result = sync.update_db(
            lock=None,
            new_permissions=[rejected, accepted],
            source_string="test",
            connector_id=2,
            credential_id=3,
            task_logger=Mock() if with_logger else None,
        )

    assert result == PermissionSyncResult(num_updated=1, num_errors=1)
    if element_kind == "document":
        classify_documents.assert_called_once_with(
            "public",
            ["accepted-document"],
            2,
            3,
        )
    else:
        classify_documents.assert_not_called()
    update_permissions.assert_called_once_with(
        "public",
        accepted,
        "test",
        2,
        3,
        {"accepted-document"} if element_kind == "document" else set(),
    )


def test_streamed_documents_classify_once_per_batch_and_count_errors() -> None:
    document_count = DOCUMENT_PERMISSION_SYNC_BATCH_SIZE * 2 + 3
    permissions = [
        DocExternalAccess(
            external_access=ExternalAccess.empty(),
            doc_id=f"document-{index}",
        )
        for index in range(document_count)
    ]
    failed_document_id = f"document-{DOCUMENT_PERMISSION_SYNC_BATCH_SIZE + 1}"

    def update_permission(
        _tenant_id: str,
        permission: ElementExternalAccess,
        _source_string: str,
        _connector_id: int,
        _credential_id: int,
        _multi_source_document_ids: set[str],
    ) -> bool:
        if (
            isinstance(permission, DocExternalAccess)
            and permission.doc_id == failed_document_id
        ):
            raise RuntimeError("test failure")
        return True

    update_permissions = Mock(side_effect=update_permission)
    classify_documents = Mock(return_value=set())

    def resolve_implementation(_module: str, function_name: str) -> Mock:
        if function_name == "element_update_permissions":
            return update_permissions
        return classify_documents

    sync = RedisConnectorPermissionSync("public", 1, Mock(spec=TenantRedisClient))
    callback = Mock()
    callback.should_stop.return_value = False
    with patch(
        "onyx.redis.redis_connector_doc_perm_sync.fetch_versioned_implementation",
        side_effect=resolve_implementation,
    ):
        result = _update_streamed_permissions(
            permissions=permissions,
            redis_permissions=sync,
            callback=callback,
            lock=Mock(spec=RedisLock),
            source_string="test",
            connector_id=2,
            credential_id=3,
            cc_pair_id=4,
            task_log=Mock(spec=Logger),
        )

    assert result == PermissionSyncResult(
        num_updated=document_count - 1,
        num_errors=1,
    )
    assert classify_documents.call_count == 3
    classified_batches = [call.args[1] for call in classify_documents.call_args_list]
    assert [len(batch) for batch in classified_batches] == [
        DOCUMENT_PERMISSION_SYNC_BATCH_SIZE,
        DOCUMENT_PERMISSION_SYNC_BATCH_SIZE,
        3,
    ]
    assert classified_batches[-1] == [
        f"document-{document_count - 3}",
        f"document-{document_count - 2}",
        f"document-{document_count - 1}",
    ]


def test_streamed_hierarchy_permissions_are_not_document_batched() -> None:
    first_document = DocExternalAccess(
        external_access=ExternalAccess.empty(),
        doc_id="first-document",
    )
    hierarchy_node = NodeExternalAccess(
        external_access=ExternalAccess.empty(),
        raw_node_id="hierarchy-node",
        source="test",
    )
    second_document = DocExternalAccess(
        external_access=ExternalAccess.empty(),
        doc_id="second-document",
    )
    redis_permissions = Mock(spec=RedisConnectorPermissionSync)
    redis_permissions.update_db.side_effect = [
        PermissionSyncResult(num_updated=1, num_errors=0),
        PermissionSyncResult(num_updated=0, num_errors=1),
        PermissionSyncResult(num_updated=1, num_errors=0),
    ]
    callback = Mock()
    callback.should_stop.return_value = False

    result = _update_streamed_permissions(
        permissions=[first_document, hierarchy_node, second_document],
        redis_permissions=redis_permissions,
        callback=callback,
        lock=Mock(spec=RedisLock),
        source_string="test",
        connector_id=2,
        credential_id=3,
        cc_pair_id=4,
        task_log=Mock(spec=Logger),
    )

    assert result == PermissionSyncResult(num_updated=2, num_errors=1)
    batches = [
        call.kwargs["new_permissions"]
        for call in redis_permissions.update_db.call_args_list
    ]
    assert batches == [[first_document], [hierarchy_node], [second_document]]
