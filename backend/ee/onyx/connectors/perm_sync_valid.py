from collections.abc import Callable
from typing import Any

from onyx.configs.constants import DocumentSource
from onyx.connectors.box.connector import BoxConnector
from onyx.connectors.canvas.connector import CanvasConnector
from onyx.connectors.confluence.connector import ConfluenceConnector
from onyx.connectors.factory import identify_connector_class
from onyx.connectors.google_drive.connector import GoogleDriveConnector
from onyx.connectors.interfaces import BaseConnector
from onyx.connectors.sharepoint.connector import SharepointConnector


def validate_canvas_perm_sync(connector: CanvasConnector) -> None:
    connector.probe_course_user_email_visibility()
    connector.probe_account_user_listing_permission()


def validate_confluence_perm_sync(connector: ConfluenceConnector) -> None:
    """
    Validate that the connector is configured correctly for permissions syncing.

    For Confluence Data Center 9.1+, the REST space-permissions endpoint
    returns HTTP 500 (rather than 403) for non-admin callers
    (CONFSERVER-99908). Probe it once during validation so a missing-admin
    misconfiguration surfaces at connector creation time -- with an
    actionable InsufficientPermissionsError -- instead of as a
    per-space-per-sync HTTP 500 with no clear remediation.
    """
    connector.probe_rest_space_permissions_admin_access()


def validate_drive_perm_sync(connector: GoogleDriveConnector) -> None:
    """
    Validate that the connector is configured correctly for permissions syncing.

    Group sync calls `admin.directory.users.get` for the configured primary
    admin. Probe it here so a misconfigured primary admin (403) fails at
    connector creation instead of every external-group-sync tick.
    """
    connector.probe_directory_admin_permission()


def validate_box_perm_sync(connector: BoxConnector) -> None:
    """
    Group sync enumerates enterprise groups and users, which the indexing path
    never touches. Probe those scopes here so a Box app missing the 'Manage
    groups' / 'Manage users' scopes fails at connector creation instead of
    every group-sync tick.
    """
    connector.probe_group_listing_permission()


def validate_sharepoint_perm_sync(connector: SharepointConnector) -> None:
    """
    Validate that the connector is configured correctly for permissions syncing.

    Two distinct permission surfaces are needed for SharePoint perm sync,
    neither of which the non-perm-sync indexing path requires:
      1. SharePoint REST 'Sites.FullControl.All' to enumerate RoleAssignments.
      2. Microsoft Graph 'GroupMember.Read.All' (or equivalent) to expand
         Azure AD groups attached to those RoleAssignments.
    Probe both here so misconfigured apps fail fast at connector creation
    instead of mid-index.
    """
    connector.probe_role_assignments_permission()
    connector.probe_group_members_permission()


# The single source of truth for which connectors carry a real perm-sync probe:
# ``validate_perm_sync`` dispatches through it, and the capability check
# framework derives probe-bearing sources from it via
# ``source_has_perm_sync_probe``. Values take the matching connector subclass;
# ``Any`` because a heterogeneous dict cannot express the per-entry pairing.
_VALIDATOR_BY_CONNECTOR_CLASS: dict[type[BaseConnector], Callable[[Any], None]] = {
    BoxConnector: validate_box_perm_sync,
    CanvasConnector: validate_canvas_perm_sync,
    ConfluenceConnector: validate_confluence_perm_sync,
    GoogleDriveConnector: validate_drive_perm_sync,
    SharepointConnector: validate_sharepoint_perm_sync,
}


def validate_perm_sync(connector: BaseConnector) -> None:
    """
    Override this if your connector needs to validate permissions syncing.
    Raise an exception if invalid, otherwise do nothing.

    Default is a no-op (always successful).
    """
    for connector_class, validator in _VALIDATOR_BY_CONNECTOR_CLASS.items():
        if isinstance(connector, connector_class):
            validator(connector)
            return


def source_has_perm_sync_probe(source: DocumentSource) -> bool:
    """
    Returns whether ``validate_perm_sync`` reaches a real probe for a source.

    Mirrors the isinstance dispatch above (``issubclass``, so a connector class
    deriving from a probe-bearing one counts the same way). Only meaningful for
    sources with a connector class; callers gate on sync-capability first.
    """
    connector_class = identify_connector_class(source)
    return any(
        issubclass(connector_class, probe_class)
        for probe_class in _VALIDATOR_BY_CONNECTOR_CLASS
    )
