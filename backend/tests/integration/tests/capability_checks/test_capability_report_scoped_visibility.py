"""EE-only visibility tests: connector-scoped reports are cc-pair data.

A scoped group manager reaches the report endpoints via ``allow_scope`` GATE 1
and passes the credential gate only for credentials they own. The connector
scope needs its own GATE 2: without it, the caller-picked ``connector_id``
would surface pairing outcomes (verdicts, probe errors, config hash) from
groups the caller does not belong to. Failed-creation orphan rows (no cc-pair
was ever created) stay a global-manager support surface.
"""

import os
from typing import Any
from uuid import uuid4

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.capability_checks.recorder import (
    record_blocking_validation_outcome,
)
from onyx.connectors.models import InputType
from onyx.db.enums import AccessType, CapabilityCheckTrigger
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.http_client import client
from tests.integration.common_utils.managers.cc_pair import CCPairManager
from tests.integration.common_utils.managers.connector import ConnectorManager
from tests.integration.common_utils.managers.credential import CredentialManager
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.managers.user_group import UserGroupManager
from tests.integration.common_utils.test_models import DATestUser

_CONNECTOR_CONFIG: dict[str, Any] = {"channels": ["general"]}

_REPORTS_FOR_SOURCE_URL = f"{API_SERVER_URL}/manage/admin/credential/capability-reports"


def _seed_report_row(credential_id: int, connector_id: int) -> None:
    """Writes one connector-scoped row the way the production blocking paths do."""
    record_blocking_validation_outcome(
        credential_id=credential_id,
        connector_id=connector_id,
        source=DocumentSource.SLACK,
        trigger=CapabilityCheckTrigger.CC_PAIR_VALIDATION,
        error=None,
        perm_sync_validated=False,
        connector_specific_config=_CONNECTOR_CONFIG,
    )


def _get_report(
    credential_id: int, connector_id: int, user: DATestUser
) -> dict[str, Any] | None:
    response = client.get(
        f"{API_SERVER_URL}/manage/admin/credential/{credential_id}/capability-report",
        params={"connector_id": connector_id},
        headers=user.headers,
    )
    response.raise_for_status()
    return response.json()


@pytest.mark.skipif(
    os.environ.get("ENABLE_PAID_ENTERPRISE_EDITION_FEATURES", "").lower() != "true",
    reason="Scoped group managers are enterprise only",
)
def test_scoped_manager_sees_only_their_groups_pairings(
    admin_user: DATestUser,
) -> None:
    # Precondition. A scoped manager owning a credential probed against three
    # connectors: one paired inside their group, one paired in a foreign
    # group, and one whose pairing was never created (failed-creation orphan).
    # Run-unique names keep re-runs against a shared DB collision-free.
    suffix = uuid4().hex[:8]
    manager = UserManager.create(name=f"scoped_manager_{suffix}")
    managed_group = UserGroupManager.create(
        name=f"managed_group_{suffix}",
        user_ids=[manager.id],
        cc_pair_ids=[],
        user_performing_action=admin_user,
    )
    foreign_group = UserGroupManager.create(
        name=f"foreign_group_{suffix}",
        user_ids=[],
        cc_pair_ids=[],
        user_performing_action=admin_user,
    )
    UserGroupManager.wait_for_sync(
        user_groups_to_check=[managed_group, foreign_group],
        user_performing_action=admin_user,
    )
    set_manager_response = UserGroupManager.set_manager(
        user_group=managed_group,
        user=manager,
        is_manager=True,
        user_performing_action=admin_user,
    )
    assert set_manager_response.status_code == 200
    # Group edits mark the group as syncing; cc-pair creation refuses to
    # relate a group mid-sync, so wait again before pairing.
    UserGroupManager.wait_for_sync(
        user_groups_to_check=[managed_group, foreign_group],
        user_performing_action=admin_user,
    )
    credential = CredentialManager.create(
        source=DocumentSource.SLACK,
        # The admin-side assertions read the same credential; the scoped path
        # only needs ownership.
        admin_public=True,
        curator_public=False,
        groups=[],
        user_performing_action=manager,
    )
    # POLL: the Slack connector is checkpoint-based and pairing rejects the
    # manager's LOAD_STATE default at connector instantiation.
    in_group_connector = ConnectorManager.create(
        source=DocumentSource.SLACK,
        input_type=InputType.POLL,
        connector_specific_config=_CONNECTOR_CONFIG,
        user_performing_action=admin_user,
    )
    foreign_connector = ConnectorManager.create(
        source=DocumentSource.SLACK,
        input_type=InputType.POLL,
        connector_specific_config=_CONNECTOR_CONFIG,
        user_performing_action=admin_user,
    )
    orphan_connector = ConnectorManager.create(
        source=DocumentSource.SLACK,
        input_type=InputType.POLL,
        connector_specific_config=_CONNECTOR_CONFIG,
        user_performing_action=admin_user,
    )
    CCPairManager.create(
        connector_id=in_group_connector.id,
        credential_id=credential.id,
        access_type=AccessType.PRIVATE,
        groups=[managed_group.id],
        user_performing_action=admin_user,
    )
    CCPairManager.create(
        connector_id=foreign_connector.id,
        credential_id=credential.id,
        access_type=AccessType.PRIVATE,
        groups=[foreign_group.id],
        user_performing_action=admin_user,
    )
    for connector_id in (
        in_group_connector.id,
        foreign_connector.id,
        orphan_connector.id,
    ):
        _seed_report_row(credential.id, connector_id)

    # Under test and postcondition. The manager sees only their group's
    # pairing; hidden pairings read as absent, like rows that never existed.
    assert _get_report(credential.id, in_group_connector.id, manager) is not None
    assert _get_report(credential.id, foreign_connector.id, manager) is None
    assert _get_report(credential.id, orphan_connector.id, manager) is None

    # The per-source listing applies the same gate.
    response = client.get(
        _REPORTS_FOR_SOURCE_URL,
        params={"source": DocumentSource.SLACK.value},
        headers=manager.headers,
    )
    response.raise_for_status()
    listed_connector_ids = {row["connector_id"] for row in response.json()}
    assert in_group_connector.id in listed_connector_ids
    assert foreign_connector.id not in listed_connector_ids
    assert orphan_connector.id not in listed_connector_ids

    # Global managers are unaffected, the orphan included (support surface).
    for connector_id in (
        in_group_connector.id,
        foreign_connector.id,
        orphan_connector.id,
    ):
        assert _get_report(credential.id, connector_id, admin_user) is not None
