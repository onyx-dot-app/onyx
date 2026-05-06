from onyx.connectors.confluence.connector import ConfluenceConnector
from onyx.connectors.google_drive.connector import GoogleDriveConnector
from onyx.connectors.interfaces import BaseConnector
from onyx.connectors.sharepoint.connector import SharepointConnector


def validate_confluence_perm_sync(connector: ConfluenceConnector) -> None:
    """
    Validate that the connector is configured correctly for permissions syncing.
    """


def validate_drive_perm_sync(connector: GoogleDriveConnector) -> None:
    """
    Validate that the connector is configured correctly for permissions syncing.
    """


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


def validate_perm_sync(connector: BaseConnector) -> None:
    """
    Override this if your connector needs to validate permissions syncing.
    Raise an exception if invalid, otherwise do nothing.

    Default is a no-op (always successful).
    """
    if isinstance(connector, ConfluenceConnector):
        validate_confluence_perm_sync(connector)
    elif isinstance(connector, GoogleDriveConnector):
        validate_drive_perm_sync(connector)
    elif isinstance(connector, SharepointConnector):
        validate_sharepoint_perm_sync(connector)
