from unittest.mock import Mock, patch

import pytest

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

    with patch(
        "onyx.redis.redis_connector_doc_perm_sync.fetch_versioned_implementation"
    ) as resolve_update:
        result = sync.update_db(
            lock=None,
            new_permissions=[rejected, accepted],
            source_string="test",
            connector_id=2,
            credential_id=3,
            task_logger=Mock() if with_logger else None,
        )

    assert result == PermissionSyncResult(num_updated=1, num_errors=1)
    resolve_update.return_value.assert_called_once_with(
        "public", accepted, "test", 2, 3
    )
