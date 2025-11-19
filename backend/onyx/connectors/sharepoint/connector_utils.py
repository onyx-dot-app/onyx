from typing import Any

from office365.graph_client import GraphClient  # type: ignore[import-untyped]
from office365.onedrive.driveitems.driveItem import DriveItem  # type: ignore[import-untyped]
from office365.sharepoint.client_context import ClientContext  # type: ignore[import-untyped]

from onyx.connectors.models import ExternalAccess
from onyx.utils.variable_functionality import (
    fetch_versioned_implementation_with_fallback,
)


def get_sharepoint_external_access(
    ctx: ClientContext,
    graph_client: GraphClient,
    drive_item: DriveItem | None = None,
    drive_name: str | None = None,
    site_page: dict[str, Any] | None = None,
    add_prefix: bool = False,
) -> ExternalAccess:
    if drive_item and drive_item.id is None:
        raise ValueError("DriveItem ID is required")

    # Get external access using the EE implementation
    def noop_fallback(*args: Any, **kwargs: Any) -> ExternalAccess:
        return ExternalAccess.empty()

    get_external_access_func = fetch_versioned_implementation_with_fallback(
        "onyx.external_permissions.sharepoint.permission_utils",
        "get_external_access_from_sharepoint",
        fallback=noop_fallback,
    )

    external_access = get_external_access_func(
        ctx, graph_client, drive_name, drive_item, site_page, add_prefix
    )

    return external_access
