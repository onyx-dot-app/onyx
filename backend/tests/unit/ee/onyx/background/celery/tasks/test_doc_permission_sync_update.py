from unittest.mock import patch

import pytest

from ee.onyx.background.celery.tasks.doc_permission_syncing import tasks as perm_tasks
from onyx.access.models import (
    DocExternalAccess,
    ElementExternalAccess,
    ExternalAccess,
    NodeExternalAccess,
)


@pytest.mark.parametrize("element_kind", ["document", "node"])
def test_oversized_acl_counts_as_error_and_continues(element_kind: str) -> None:
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
    with patch.object(perm_tasks, "element_update_permissions") as update_element:
        result = perm_tasks.update_element_permissions_batch(
            tenant_id="public",
            new_permissions=[rejected, accepted],
            source_string="test",
            connector_id=2,
            credential_id=3,
        )

    assert result == perm_tasks.PermissionSyncResult(num_updated=1, num_errors=1)
    update_element.assert_called_once_with("public", accepted, "test", 2, 3)
