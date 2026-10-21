"""Site, group and gateway builders that the SharePoint capability check tests share."""

from typing import Any
from unittest.mock import MagicMock, create_autospec

from onyx.connectors.microsoft_utils.drive_delta import (
    DriveDeltaFetchResult,
    DriveDeltaPage,
)
from onyx.connectors.microsoft_utils.entra import EntraGroup, EntraPage
from onyx.connectors.microsoft_utils.graph_auth import MicrosoftAuthMethod
from onyx.connectors.microsoft_utils.graph_errors import MicrosoftGraphError
from onyx.connectors.microsoft_utils.models import (
    SharepointPrincipal,
    SharepointRoleAssignment,
)
from onyx.connectors.microsoft_utils.sharepoint_principals import (
    SharepointPrincipalType,
)
from onyx.connectors.sharepoint.models import (
    SharepointDrive,
    SitePagesPage,
    SiteUrlListing,
)
from onyx.connectors.sharepoint.source_operations import SharepointSourceOperations

SITE_URL = "https://contoso.sharepoint.com/sites/eng"
OTHER_SITE_URL = "https://contoso.sharepoint.com/sites/ops"
GROUP_ID = "11111111-1111-1111-1111-111111111111"
CLAIMS_LOGIN = f"c:0t.c|tenant|{GROUP_ID}"
DRIVE = SharepointDrive(
    id="drive-id",
    name="Documents",
    web_url=f"{SITE_URL}/Shared%20Documents",
    list_id="list-id",
)
ITEM_JSON: dict[str, Any] = {
    "id": "item-id",
    "name": "plan.pdf",
    "webUrl": f"{SITE_URL}/Shared%20Documents/Plans/plan.pdf",
    "size": 10,
    "file": {"mimeType": "application/pdf"},
    "parentReference": {"driveId": "drive-id", "path": "/drives/d/root:/Plans"},
}


def make_assignment(
    principal_type: SharepointPrincipalType,
    login_name: str,
    title: str | None = None,
    role_type_kinds: list[int] | None = None,
) -> SharepointRoleAssignment:
    return SharepointRoleAssignment(
        member=SharepointPrincipal(
            principal_type=principal_type,
            login_name=login_name,
            title=title or login_name,
        ),
        role_type_kinds=[3] if role_type_kinds is None else role_type_kinds,
    )


SITE_GROUP = make_assignment(SharepointPrincipalType.SHAREPOINT_GROUP, "Eng Members")
ENTRA_GROUP = make_assignment(
    SharepointPrincipalType.ENTRA_GROUP, CLAIMS_LOGIN, "Engineering"
)


def api_refusal(status: int, code: str = "accessDenied") -> MicrosoftGraphError:
    return MicrosoftGraphError(status, code, "refused")


def delta_result(*items: dict[str, Any]) -> DriveDeltaFetchResult:
    return DriveDeltaFetchResult(
        page=DriveDeltaPage.model_validate({"value": list(items)})
    )


def healthy_gateway() -> MagicMock:
    """A certificate app on a tenant with one site naming a site group and an
    Entra group, holding one library with one file in a folder and one page."""
    gateway: MagicMock = create_autospec(SharepointSourceOperations, instance=True)
    gateway.get_auth_method.return_value = MicrosoftAuthMethod.CERTIFICATE
    gateway.list_site_urls.return_value = SiteUrlListing(
        site_urls=[SITE_URL, OTHER_SITE_URL], complete=True
    )
    gateway.get_site_id.return_value = "site-id"
    gateway.list_drives.return_value = [DRIVE]
    gateway.get_delta_page.return_value = delta_result(ITEM_JSON)
    gateway.list_site_pages.return_value = SitePagesPage(
        pages=[{"id": "page-id", "webUrl": f"{SITE_URL}/SitePages/Home.aspx"}]
    )
    gateway.list_role_assignments.return_value = [SITE_GROUP, ENTRA_GROUP]
    gateway.list_site_group_users.return_value = []
    gateway.find_entra_group_id.return_value = GROUP_ID
    gateway.list_nested_entra_groups.return_value = []
    gateway.list_entra_group_members.return_value = []
    gateway.get_folder_unique_id.return_value = "folder-id"
    gateway.get_list_item_id.return_value = 7
    gateway.list_sharing_link_scopes.return_value = []
    gateway.list_entra_groups.return_value = EntraPage(
        items=[EntraGroup(id=GROUP_ID, displayName="Engineering")]
    )
    gateway.list_entra_group_member_page.return_value = EntraPage(items=[])
    return gateway
