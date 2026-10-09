"""Auto-discovering coverage harness for source operations.

For every registered gateway, every (operation, variant) unit must be exercised,
per capability tag, by a capability check of that capability -- unless the
operation carries an ``untested`` reason. A per-connector session that registers
a gateway is picked up here automatically; it cannot forget to wire the test.
"""

from collections.abc import Callable
from typing import Any
from unittest.mock import MagicMock

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.capability_checks.registry import get_capability_checks
from onyx.connectors.confluence.source_operations import (
    ConfluenceRestSpacePermissionsNotAvailableError,
    ConfluenceSpacePermissionsVariant,
)
from onyx.connectors.google_drive.models import GDriveMimeType
from onyx.connectors.google_drive.source_operations import (
    GoogleDriveAuth,
    GoogleGroupMember,
)
from onyx.connectors.google_utils.shared_constants import GoogleCredentialKind
from onyx.connectors.source_operations import (
    SourceOperations,
    registered_source_operations,
)
from tests.unit.onyx.connectors.source_operation_harnesses import (
    compute_uncovered_units,
    import_all_source_operation_gateways,
)

import_all_source_operation_gateways()


def _configure_confluence_spy(spy: MagicMock) -> None:
    """A DC 9.1+ site whose REST space-permissions endpoint is missing: the
    checks try REST and then fall back to JSON-RPC, so both DC units run."""

    def get_space_permissions(
        *, variant: ConfluenceSpacePermissionsVariant, **_kwargs: Any
    ) -> list[dict[str, Any]]:
        if variant == ConfluenceSpacePermissionsVariant.DC_REST:
            raise ConfluenceRestSpacePermissionsNotAvailableError("coverage spy")
        return []

    spy.get_server_version.return_value = (9, 1)
    spy.get_space_permissions.side_effect = get_space_permissions


def _configure_google_drive_spy(spy: MagicMock) -> None:
    """A service account whose primary admin sees a Google Doc, a small
    upload, a shared drive file and a folder whose permissions come only by
    id, and one shared drive, organized through a group."""
    admin = "admin@example.com"
    sample = [
        {"id": "doc", "name": "doc", "mimeType": GDriveMimeType.DOC.value},
        {"id": "pdf", "name": "pdf", "mimeType": "application/pdf", "size": "10"},
        {"id": "shared", "name": "shared", "permissionIds": ["permission"]},
    ]
    spy.authenticate.return_value = GoogleDriveAuth(
        kind=GoogleCredentialKind.SERVICE_ACCOUNT, primary_admin_email=admin
    )
    spy.list_files.side_effect = lambda **_kwargs: iter(sample)
    spy.list_drives.side_effect = lambda **_kwargs: iter(["drive"])
    spy.list_drive_members.side_effect = lambda **_kwargs: iter(
        [{"emailAddress": "team@example.com", "type": "group", "role": "organizer"}]
    )
    spy.list_group_members.side_effect = lambda **_kwargs: iter(
        [GoogleGroupMember(email="organizer@example.com", type="USER")]
    )
    spy.list_user_emails.side_effect = lambda **_kwargs: iter([admin])
    spy.can_list_drive.return_value = True
    spy.list_folders_with_permissions.side_effect = lambda **_kwargs: iter(
        [{"id": "folder", "name": "folder", "permissionIds": ["permission"]}]
    )
    spy.list_file_permissions.side_effect = lambda **_kwargs: iter(
        [{"id": "permission"}]
    )


_SPY_CONFIGURATIONS: dict[DocumentSource, Callable[[MagicMock], None]] = {
    DocumentSource.CONFLUENCE: _configure_confluence_spy,
    DocumentSource.GOOGLE_DRIVE: _configure_google_drive_spy,
}


@pytest.mark.usefixtures("enable_ee")
@pytest.mark.parametrize(
    "gateway_class",
    list(registered_source_operations().values()),
    ids=lambda gateway_class: gateway_class.source.value,
)
def test_every_operation_unit_is_exercised_by_a_check(
    gateway_class: type[SourceOperations],
) -> None:
    """Verifies check coverage of every non-exempt (operation, variant) unit.

    Runs with EE enabled: perm-sync checks live only in the EE registries, so
    perm-sync-tagged units are coverable only when EE resolution is on.
    """
    # Precondition.
    checks = get_capability_checks(gateway_class.source)

    # Under test.
    uncovered = compute_uncovered_units(
        gateway_class, checks, _SPY_CONFIGURATIONS.get(gateway_class.source)
    )

    # Postcondition.
    assert not uncovered, (
        f"{gateway_class.source.value} has operation units no capability "
        f"check exercises: {uncovered}. Add a check composing them "
        '(variant-bearing operations must be invoked with variant="<name>") '
        'or annotate the operation untested="<reason>".'
    )
