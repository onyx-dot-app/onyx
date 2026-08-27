"""EE-only visibility tests: connector-scoped reports are management data.

A scoped group manager reaches the report endpoints via ``allow_scope`` GATE 1.
GATE 2 splits by scope: the credential scope follows credential visibility
(creator-only for scoped managers), while the connector scope follows pairing
visibility alone, bound to the caller's MANAGED scope -- read visibility would
surface pairing outcomes (verdicts, probe errors, config hash) from every public
or sync pairing, and is skipped entirely for READ_CONNECTORS holders. Pairing
visibility does not require credential visibility: whoever manages the pairing
may read its outcomes, as on the cc-pair detail endpoint. Failed-creation orphan
rows (no cc-pair was ever created) stay a global-manager support surface.
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
from onyx.db.enums import AccessType, CapabilityCheckTrigger, Permission
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.http_client import client
from tests.integration.common_utils.managers.cc_pair import CCPairManager
from tests.integration.common_utils.managers.connector import ConnectorManager
from tests.integration.common_utils.managers.credential import CredentialManager
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.managers.user_group import UserGroupManager
from tests.integration.common_utils.test_models import DATestUser, DATestUserGroup

_CONNECTOR_CONFIG: dict[str, Any] = {"channels": ["general"]}

_REPORTS_FOR_SOURCE_URL = f"{API_SERVER_URL}/manage/admin/credential/capability-reports"


def _bootstrap_scoped_manager(
    admin_user: DATestUser, suffix: str
) -> tuple[DATestUser, DATestUserGroup]:
    """
    Creates a scoped manager and their managed group, synced and ready to pair.
    """
    manager = UserManager.create(name=f"scoped_manager_{suffix}")
    managed_group = UserGroupManager.create(
        name=f"managed_group_{suffix}",
        user_ids=[manager.id],
        cc_pair_ids=[],
        user_performing_action=admin_user,
    )
    UserGroupManager.wait_for_sync(
        user_groups_to_check=[managed_group],
        user_performing_action=admin_user,
    )
    set_manager_response = UserGroupManager.set_manager(
        user_group=managed_group,
        user=manager,
        is_manager=True,
        user_performing_action=admin_user,
    )
    assert set_manager_response.status_code == 200
    # Group edits mark the group as syncing; cc-pair creation refuses to relate
    # a group mid-sync, so wait again before pairing.
    UserGroupManager.wait_for_sync(
        user_groups_to_check=[managed_group],
        user_performing_action=admin_user,
    )
    return manager, managed_group


def _seed_report_row(credential_id: int, connector_id: int) -> None:
    """
    Writes one connector-scoped row the way the production blocking paths do.
    """
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
    # Precondition.
    # A scoped manager owning a credential probed against four connectors:
    # paired in their managed group, paired in a foreign group, paired publicly
    # (read-visible to everyone, managed by nobody here), and never successfully
    # paired (failed-creation orphan). Run-unique names keep re-runs against a
    # shared DB collision-free.
    suffix = uuid4().hex[:8]
    manager, managed_group = _bootstrap_scoped_manager(admin_user, suffix)
    foreign_group = UserGroupManager.create(
        name=f"foreign_group_{suffix}",
        user_ids=[],
        cc_pair_ids=[],
        user_performing_action=admin_user,
    )
    UserGroupManager.wait_for_sync(
        user_groups_to_check=[foreign_group],
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
    public_connector = ConnectorManager.create(
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
    CCPairManager.create(
        connector_id=public_connector.id,
        credential_id=credential.id,
        access_type=AccessType.PUBLIC,
        user_performing_action=admin_user,
    )
    hidden_connector_ids = (
        foreign_connector.id,
        public_connector.id,
        orphan_connector.id,
    )
    for connector_id in (in_group_connector.id, *hidden_connector_ids):
        _seed_report_row(credential.id, connector_id)

    # Under test and postcondition.
    # The manager sees only the pairing they manage; everything else -- foreign
    # group, public (merely read-visible), orphan -- reads as absent, like rows
    # that never existed.
    assert _get_report(credential.id, in_group_connector.id, manager) is not None
    for connector_id in hidden_connector_ids:
        assert _get_report(credential.id, connector_id, manager) is None

    # The per-source listing applies the same gate.
    response = client.get(
        _REPORTS_FOR_SOURCE_URL,
        params={"source": DocumentSource.SLACK.value},
        headers=manager.headers,
    )
    response.raise_for_status()
    listed_connector_ids = {row["connector_id"] for row in response.json()}
    assert in_group_connector.id in listed_connector_ids
    for connector_id in hidden_connector_ids:
        assert connector_id not in listed_connector_ids

    # A global grant that only implies READ_CONNECTORS (which skips the cc-pair
    # read filter entirely) must not widen the gate: read visibility is not
    # management scope.
    UserGroupManager.wait_for_sync(
        user_groups_to_check=[managed_group],
        user_performing_action=admin_user,
    )
    set_permissions_response = UserGroupManager.set_permissions(
        user_group=managed_group,
        permissions=[Permission.MANAGE_DOCUMENT_SETS.value],
        user_performing_action=admin_user,
    )
    assert set_permissions_response.status_code == 200
    assert Permission.READ_CONNECTORS.value in UserManager.get_permissions(manager)
    assert _get_report(credential.id, in_group_connector.id, manager) is not None
    for connector_id in hidden_connector_ids:
        assert _get_report(credential.id, connector_id, manager) is None

    # Global managers are unaffected, the orphan included (support surface).
    for connector_id in (in_group_connector.id, *hidden_connector_ids):
        assert _get_report(credential.id, connector_id, admin_user) is not None


@pytest.mark.skipif(
    os.environ.get("ENABLE_PAID_ENTERPRISE_EDITION_FEATURES", "").lower() != "true",
    reason="Scoped group managers are enterprise only",
)
def test_managed_pairing_is_readable_without_credential_visibility(
    admin_user: DATestUser,
) -> None:
    # Precondition.
    # An admin-created credential paired into the manager's managed group. The
    # credential filter is creator-only for scoped managers (``admin_public``
    # notwithstanding), so the credential itself is invisible to them; only
    # pairing visibility can admit its report.
    suffix = uuid4().hex[:8]
    manager, managed_group = _bootstrap_scoped_manager(admin_user, suffix)
    credential = CredentialManager.create(
        source=DocumentSource.SLACK,
        admin_public=True,
        curator_public=False,
        groups=[],
        user_performing_action=admin_user,
    )
    connector = ConnectorManager.create(
        source=DocumentSource.SLACK,
        input_type=InputType.POLL,
        connector_specific_config=_CONNECTOR_CONFIG,
        user_performing_action=admin_user,
    )
    CCPairManager.create(
        connector_id=connector.id,
        credential_id=credential.id,
        access_type=AccessType.PRIVATE,
        groups=[managed_group.id],
        user_performing_action=admin_user,
    )
    _seed_report_row(credential.id, connector.id)

    # Under test and postcondition.
    # Pairing visibility alone authorizes the connector-scoped read; the
    # credential scope stays gated on credential visibility and reads as
    # inaccessible.
    assert _get_report(credential.id, connector.id, manager) is not None
    credential_scope_response = client.get(
        f"{API_SERVER_URL}/manage/admin/credential/{credential.id}/capability-report",
        headers=manager.headers,
    )
    assert credential_scope_response.status_code == 404
    error_code = credential_scope_response.json()["error_code"]
    assert error_code == "CREDENTIAL_NOT_FOUND"

    # The per-source listing admits the managed pairing's row the same way.
    listing_response = client.get(
        _REPORTS_FOR_SOURCE_URL,
        params={"source": DocumentSource.SLACK.value},
        headers=manager.headers,
    )
    listing_response.raise_for_status()
    listed_connector_ids = {row["connector_id"] for row in listing_response.json()}
    assert connector.id in listed_connector_ids
