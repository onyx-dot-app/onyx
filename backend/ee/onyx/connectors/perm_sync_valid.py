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

    SharePoint RoleAssignments enumeration uses the SharePoint REST surface,
    which is granted separately from the Graph permissions used by the
    non-perm-sync indexing path. Probe it here so non-perm-sync connectors
    aren't forced to grant 'Sites.FullControl.All'.
    """
    connector.probe_role_assignments_permission()


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
