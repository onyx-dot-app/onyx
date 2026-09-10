import copy
import fnmatch
import html
import os
import re
import time
from collections import deque
from collections.abc import Generator, Iterable
from datetime import datetime, timezone
from typing import Any, cast
from urllib.parse import unquote, urlsplit

import msal
import requests
from office365.graph_client import GraphClient
from office365.onedrive.sites.site import Site
from office365.onedrive.sites.sites_with_root import SitesWithRoot
from office365.runtime.auth.token_response import TokenResponse
from office365.runtime.client_request import ClientRequestException
from office365.sharepoint.client_context import ClientContext
from pydantic import BaseModel, Field
from requests.exceptions import HTTPError
from typing_extensions import override

from onyx.configs.app_configs import (
    INDEX_BATCH_SIZE,
    SHAREPOINT_CONNECTOR_SIZE_THRESHOLD,
)
from onyx.configs.constants import DocumentSource
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.interfaces import (
    CheckpointedConnectorWithPermSync,
    CheckpointOutput,
    GenerateSlimDocumentOutput,
    IndexingHeartbeatInterface,
    Resolver,
    SecondsSinceUnixEpoch,
    SlimConnector,
    SlimConnectorWithPermSync,
)
from onyx.connectors.microsoft_utils.drive_items import (
    DriveItemContentError,
    DriveItemData,
    build_delta_start_url,
    build_item_relative_path,
    extract_drive_item_content,
    extract_folder_path_from_parent_reference,
    fetch_one_delta_page,
    is_path_excluded,
    iter_drive_items_delta,
    iter_drive_items_paged,
    parse_graph_datetime,
    timestamp_in_window,
)
from onyx.connectors.microsoft_utils.graph_auth import (
    MicrosoftAuthMethod,
    acquire_graph_token,
    build_msal_app,
)
from onyx.connectors.microsoft_utils.graph_client import (
    GraphApiClient,
    graph_error_code,
)
from onyx.connectors.microsoft_utils.graph_env import (
    DEFAULT_AUTHORITY_HOST,
    DEFAULT_GRAPH_API_HOST,
    DEFAULT_SHAREPOINT_DOMAIN_SUFFIX,
    resolve_microsoft_environment,
)
from onyx.connectors.models import (
    BasicExpertInfo,
    ConnectorCheckpoint,
    ConnectorFailure,
    ConnectorMissingCredentialError,
    Document,
    DocumentFailure,
    EntityFailure,
    ExternalAccess,
    HierarchyNode,
    SlimDocument,
    TextSection,
)
from onyx.connectors.sharepoint.connector_utils import (
    SharepointPermissionCache,
    get_sharepoint_external_access,
    get_sharepoint_hierarchy_node_external_access,
)
from onyx.db.enums import HierarchyNodeType
from onyx.file_processing.extract_file_text import get_file_ext
from onyx.file_processing.file_types import OnyxFileExtensions
from onyx.file_store.staging import RawFileCallback
from onyx.utils.logger import setup_logger
from onyx.utils.threadpool_concurrency import run_functions_tuples_in_parallel
from onyx.utils.url import SSRFException, validate_outbound_http_url

logger = setup_logger()
SLIM_BATCH_SIZE = 1000


SHARED_DOCUMENTS_MAP = {
    "Documents": "Shared Documents",
    "Dokumente": "Freigegebene Dokumente",
    "Documentos": "Documentos compartidos",
}
SHARED_DOCUMENTS_MAP_REVERSE = {v: k for k, v in SHARED_DOCUMENTS_MAP.items()}

# On OneDrive personal sites the Graph API reports the primary library's name as
# one of these, while the browser/SharePoint URL uses "Documents".
ONEDRIVE_DRIVE_NAMES = frozenset(
    {"onedrive", "onedrive for business", "documentlibrary"}
)
# `driveType` values that identify a user's primary OneDrive (as opposed to an
# extra "documentLibrary" added to the personal site). OneDrive personal returns
# "personal", OneDrive for Business returns "business".
ONEDRIVE_PRIMARY_DRIVE_TYPES = frozenset({"personal", "business"})
PERSONAL_SITE_URL_MARKER = "/personal/"

ASPX_EXTENSION = ".aspx"


def _is_site_excluded(site_url: str, excluded_site_patterns: list[str]) -> bool:
    """Check if a site URL matches any of the exclusion glob patterns."""
    for pattern in excluded_site_patterns:
        if fnmatch.fnmatch(site_url, pattern) or fnmatch.fnmatch(
            site_url.rstrip("/"), pattern.rstrip("/")
        ):
            return True
    return False


# Cap how many configured sites the perm-sync RoleAssignments probe checks at
# validation time. Each probe is one HTTP round-trip, so we trade exhaustive
# coverage for keeping connector creation responsive on tenants with many
# configured sites.
ROLE_ASSIGNMENTS_PROBE_MAX_SITES = 5


# The office365 library's ClientContext caches the access token from its
# first request and never re-invokes the token callback.  Microsoft access
# tokens live ~60-75 minutes, so we recreate the cached ClientContext every
# 30 minutes to let MSAL transparently handle token refresh.
_REST_CTX_MAX_AGE_S = 30 * 60


class SiteDescriptor(BaseModel):
    """Data class for storing SharePoint site information.

    Args:
        url: The base site URL (e.g. https://danswerai.sharepoint.com/sites/sharepoint-tests
             or https://danswerai.sharepoint.com/teams/team-name)
        drive_name: The name of the drive to access (e.g. "Shared Documents", "Other Library")
                   If None, all drives will be accessed.
        folder_path: The folder path within the drive to access (e.g. "test/nested with spaces")
                    If None, all folders will be accessed.
    """

    url: str
    drive_name: str | None
    folder_path: str | None


class SiteDrive(BaseModel):
    """A drive (document library) of a site, as listed from Graph."""

    drive_id: str
    name: str
    web_url: str | None


class ResolvedDriveItem(BaseModel):
    """The result of mapping a failed item's link back to a fetchable item."""

    driveitem: DriveItemData
    drive_name: str  # display name (SHARED_DOCUMENTS_MAP-mapped)
    drive_web_url: str | None
    site_url: str


def _site_page_in_time_window(
    page: dict[str, Any],
    start: datetime | None,
    end: datetime | None,
) -> bool:
    """Return True if the page's lastModifiedDateTime falls within [start, end]."""
    if start is None and end is None:
        return True
    last_modified = parse_graph_datetime(page.get("lastModifiedDateTime"))
    if last_modified is None:
        return True
    return timestamp_in_window(last_modified, start, end)


# `GET /sites/getAllSites` returns the tenant-wide directory of every site
# collection, not just sites the app principal can read. Per-site content
# access is gated separately, so some listed sites will always reject reads.
# 403/404/410 cover "no permission / removed / gone"; 423 ("notAllowed")
# covers admin-locked or M365-archived sites (e.g. `Set-SPOSiteArchiveState
# -ArchiveState Archived`). All four are per-site conditions — skip the
# site and continue the run rather than aborting the whole tenant index.
PER_SITE_GRAPH_FAILURE_STATUSES: frozenset[int] = frozenset({403, 404, 410, 423})


def _is_per_site_graph_failure(e: ClientRequestException | HTTPError) -> bool:
    # response=None means a wrapped transport error; the retry layer owns it.
    if e.response is None:
        return False
    return e.response.status_code in PER_SITE_GRAPH_FAILURE_STATUSES


class SharepointConnectorCheckpoint(ConnectorCheckpoint):
    cached_site_descriptors: deque[SiteDescriptor] | None = None
    current_site_descriptor: SiteDescriptor | None = None

    cached_drive_names: deque[str] | None = None
    current_drive_name: str | None = None
    # Drive's web_url from the API - used as raw_node_id for DRIVE hierarchy nodes
    current_drive_web_url: str | None = None
    # Resolved drive ID — avoids re-resolving on checkpoint resume
    current_drive_id: str | None = None
    # Next delta API page URL for per-page checkpointing within a drive.
    # When set, Phase 3b fetches one page at a time so progress is persisted
    # between pages.  None means BFS path or no active delta traversal.
    current_drive_delta_next_link: str | None = None

    process_site_pages: bool = False

    # Track yielded hierarchy nodes by their raw_node_id (URLs) to avoid duplicates
    seen_hierarchy_node_raw_ids: set[str] = Field(default_factory=set)

    # Track yielded document IDs to avoid processing the same document twice.
    # The Microsoft Graph delta API can return the same item on multiple pages.
    seen_document_ids: set[str] = Field(default_factory=set)
    permission_cache: SharepointPermissionCache = Field(
        default_factory=SharepointPermissionCache
    )


GRAPH_INVALID_REQUEST_CODE = "invalidRequest"


def _is_graph_invalid_request(response: requests.Response) -> bool:
    """Return True if the response body is the generic Graph API
    ``{"error": {"code": "invalidRequest", "message": "Invalid request"}}``
    shape. This particular error has no actionable inner error code and is
    returned by the site-pages endpoint when a page has a corrupt canvas layout
    (e.g. duplicate web-part IDs — see SharePoint/sp-dev-docs#8822)."""
    try:
        body = response.json()
    except Exception:
        return False
    error = body.get("error", {})
    return error.get("code") == GRAPH_INVALID_REQUEST_CODE


def acquire_token_for_rest(
    msal_app: msal.ConfidentialClientApplication,
    sp_tenant_domain: str,
    sharepoint_domain_suffix: str,
) -> TokenResponse:
    token = msal_app.acquire_token_for_client(
        scopes=[f"https://{sp_tenant_domain}.{sharepoint_domain_suffix}/.default"]
    )
    return TokenResponse.from_json(token)


def _probe_site_role_assignments_authorized(
    site_url: str, headers: dict[str, str]
) -> bool:
    """Issue a single RoleAssignments REST probe against `site_url`.

    Returns True if the SharePoint REST surface accepts the call (any non-401/403
    status), False if SP rejected it as unauthorized. Transport-level errors are
    swallowed and treated as authorized so a transient network blip doesn't fail
    validation; the runtime perm-sync code will surface real failures.

    Designed to be called via run_functions_tuples_in_parallel — keep it side-
    effect free aside from logging.
    """
    probe_url = f"{site_url.rstrip('/')}/_api/web/roleassignments?$top=1"
    try:
        resp = requests.get(probe_url, headers=headers, timeout=10)
    except Exception as e:
        logger.warning(
            "RoleAssignments permission probe failed for %s (non-blocking): %s",
            site_url,
            e,
        )
        return True
    return resp.status_code not in (401, 403)


def _create_document_failure(
    driveitem: DriveItemData,
    error_message: str,
    exception: Exception | None = None,
) -> ConnectorFailure:
    """Helper method to create a ConnectorFailure for document processing errors."""
    return ConnectorFailure(
        failed_document=DocumentFailure(
            document_id=driveitem.id or "unknown",
            document_link=driveitem.web_url,
        ),
        failure_message=f"SharePoint document '{driveitem.name or 'unknown'}': {error_message}",
        exception=exception,
    )


def _create_entity_failure(
    entity_id: str,
    error_message: str,
    time_range: tuple[datetime, datetime] | None = None,
    exception: Exception | None = None,
) -> ConnectorFailure:
    """Helper method to create a ConnectorFailure for entity-level errors."""
    return ConnectorFailure(
        failed_entity=EntityFailure(
            entity_id=entity_id,
            missed_time_range=time_range,
        ),
        failure_message=f"SharePoint entity '{entity_id}': {error_message}",
        exception=exception,
    )


def _convert_driveitem_to_document_with_permissions(
    driveitem: DriveItemData,
    drive_name: str,
    ctx: ClientContext | None,
    graph_client: GraphClient,
    graph_api_base: str,
    include_permissions: bool = False,
    parent_hierarchy_raw_node_id: str | None = None,
    access_token: str | None = None,
    treat_sharing_link_as_public: bool = False,
    raw_file_callback: RawFileCallback | None = None,
    permission_cache: SharepointPermissionCache | None = None,
) -> Document | ConnectorFailure | None:
    if not driveitem.name or not driveitem.id:
        raise ValueError("DriveItem name/id is required")

    if include_permissions and ctx is None:
        raise ValueError("ClientContext is required for permissions")
    permission_cache = permission_cache or SharepointPermissionCache()

    try:
        content = extract_drive_item_content(
            driveitem,
            size_threshold=SHAREPOINT_CONNECTOR_SIZE_THRESHOLD,
            graph_api_base=graph_api_base,
            access_token=access_token,
            raw_file_callback=raw_file_callback,
        )
    except DriveItemContentError as e:
        cause = e.__cause__ if isinstance(e.__cause__, Exception) else None
        return _create_document_failure(driveitem, str(e), cause)

    if content is None:
        return None

    sections = content.sections
    staged_file_id = content.staged_file_id

    if include_permissions and ctx is not None:
        logger.info("Getting external access for %s", driveitem.name)
        sdk_item = driveitem.to_sdk_driveitem(graph_client)
        external_access = get_sharepoint_external_access(
            ctx=ctx,
            graph_client=graph_client,
            permission_cache=permission_cache,
            drive_item=sdk_item,
            drive_name=drive_name,
            add_prefix=True,
            treat_sharing_link_as_public=treat_sharing_link_as_public,
        )
    else:
        external_access = ExternalAccess.empty()

    doc = Document(
        id=driveitem.id,
        sections=sections,
        source=DocumentSource.SHAREPOINT,
        semantic_identifier=driveitem.name,
        external_access=external_access,
        doc_created_at=driveitem.created_datetime,
        doc_updated_at=driveitem.last_modified_datetime,
        primary_owners=[
            BasicExpertInfo(
                display_name=driveitem.last_modified_by_display_name or "",
                email=driveitem.last_modified_by_email or "",
            )
        ],
        metadata={"drive": drive_name},
        parent_hierarchy_raw_node_id=parent_hierarchy_raw_node_id,
        file_id=staged_file_id,
    )
    return doc


def _convert_sitepage_to_document(
    site_page: dict[str, Any],
    site_name: str | None,
    ctx: ClientContext | None,
    graph_client: GraphClient,
    permission_cache: SharepointPermissionCache,
    include_permissions: bool = False,
    parent_hierarchy_raw_node_id: str | None = None,
    treat_sharing_link_as_public: bool = False,
) -> Document:
    """Convert a SharePoint site page to a Document object."""
    # Extract text content from the site page
    page_text = ""
    # Get title and description
    title = cast(str, site_page.get("title", ""))
    description = cast(str, site_page.get("description", ""))

    # Build the text content
    if title:
        page_text += f"# {title}\n\n"
    if description:
        page_text += f"{description}\n\n"

    # Extract content from canvas layout if available
    canvas_layout = site_page.get("canvasLayout", {})
    if canvas_layout:
        horizontal_sections = canvas_layout.get("horizontalSections", [])
        for section in horizontal_sections:
            columns = section.get("columns", [])
            for column in columns:
                webparts = column.get("webparts", [])
                for webpart in webparts:
                    # Extract text from different types of webparts
                    webpart_type = webpart.get("@odata.type", "")

                    # Extract text from text webparts
                    if webpart_type == "#microsoft.graph.textWebPart":
                        inner_html = webpart.get("innerHtml", "")
                        if inner_html:
                            # Basic HTML to text conversion
                            # Remove HTML tags but preserve some structure
                            text_content = re.sub(r"<br\s*/?>", "\n", inner_html)
                            text_content = re.sub(r"<li>", "• ", text_content)
                            text_content = re.sub(r"</li>", "\n", text_content)
                            text_content = re.sub(
                                r"<h[1-6][^>]*>", "\n## ", text_content
                            )
                            text_content = re.sub(r"</h[1-6]>", "\n", text_content)
                            text_content = re.sub(r"<p[^>]*>", "\n", text_content)
                            text_content = re.sub(r"</p>", "\n", text_content)
                            text_content = re.sub(r"<[^>]+>", "", text_content)
                            # Decode HTML entities
                            text_content = html.unescape(text_content)
                            # Clean up extra whitespace
                            text_content = re.sub(
                                r"\n\s*\n", "\n\n", text_content
                            ).strip()
                            if text_content:
                                page_text += f"{text_content}\n\n"

                    # Extract text from standard webparts
                    elif webpart_type == "#microsoft.graph.standardWebPart":
                        data = webpart.get("data", {})

                        # Extract from serverProcessedContent
                        server_content = data.get("serverProcessedContent", {})
                        searchable_texts = server_content.get(
                            "searchablePlainTexts", []
                        )

                        for text_item in searchable_texts:
                            if isinstance(text_item, dict):
                                key = text_item.get("key", "")
                                value = text_item.get("value", "")
                                if value:
                                    # Add context based on key
                                    if key == "title":
                                        page_text += f"## {value}\n\n"
                                    else:
                                        page_text += f"{value}\n\n"

                        # Extract description if available
                        description = data.get("description", "")
                        if description:
                            page_text += f"{description}\n\n"

                        # Extract title if available
                        webpart_title = data.get("title", "")
                        if webpart_title and webpart_title != description:
                            page_text += f"## {webpart_title}\n\n"

    page_text = page_text.strip()

    # If no content extracted, use the title as fallback
    if not page_text and title:
        page_text = title

    created_datetime = parse_graph_datetime(site_page.get("createdDateTime"))
    last_modified_datetime = parse_graph_datetime(site_page.get("lastModifiedDateTime"))

    # Extract owner information
    primary_owners = []
    created_by = site_page.get("createdBy", {}).get("user", {})
    if created_by.get("displayName"):
        primary_owners.append(
            BasicExpertInfo(
                display_name=created_by.get("displayName"),
                email=created_by.get("email", ""),
            )
        )

    web_url = site_page["webUrl"]
    semantic_identifier = cast(str, site_page.get("name", title))
    if semantic_identifier.endswith(ASPX_EXTENSION):
        semantic_identifier = semantic_identifier[: -len(ASPX_EXTENSION)]

    if include_permissions:
        external_access = get_sharepoint_external_access(
            ctx=ctx,  # ty: ignore[invalid-argument-type]
            graph_client=graph_client,
            permission_cache=permission_cache,
            site_page=site_page,
            add_prefix=True,
            treat_sharing_link_as_public=treat_sharing_link_as_public,
        )
    else:
        external_access = ExternalAccess.empty()

    doc = Document(
        id=site_page["id"],
        sections=[TextSection(link=web_url, text=page_text)],
        source=DocumentSource.SHAREPOINT,
        external_access=external_access,
        semantic_identifier=semantic_identifier,
        doc_created_at=created_datetime,
        doc_updated_at=last_modified_datetime or created_datetime,
        primary_owners=primary_owners,
        metadata=(
            {
                "site": site_name,
            }
            if site_name
            else {}
        ),
        parent_hierarchy_raw_node_id=parent_hierarchy_raw_node_id,
    )
    return doc


def _convert_driveitem_to_slim_document(
    driveitem: DriveItemData,
    drive_name: str,
    ctx: ClientContext,
    graph_client: GraphClient,
    permission_cache: SharepointPermissionCache,
    parent_hierarchy_raw_node_id: str | None = None,
    treat_sharing_link_as_public: bool = False,
) -> SlimDocument:
    if driveitem.id is None:
        raise ValueError("DriveItem ID is required")

    sdk_item = driveitem.to_sdk_driveitem(graph_client)
    external_access = get_sharepoint_external_access(
        ctx=ctx,
        graph_client=graph_client,
        permission_cache=permission_cache,
        drive_item=sdk_item,
        drive_name=drive_name,
        treat_sharing_link_as_public=treat_sharing_link_as_public,
    )

    return SlimDocument(
        id=driveitem.id,
        external_access=external_access,
        parent_hierarchy_raw_node_id=parent_hierarchy_raw_node_id,
        doc_created_at=driveitem.created_datetime,
    )


def _convert_sitepage_to_slim_document(
    site_page: dict[str, Any],
    ctx: ClientContext | None,
    graph_client: GraphClient,
    permission_cache: SharepointPermissionCache,
    parent_hierarchy_raw_node_id: str | None = None,
    treat_sharing_link_as_public: bool = False,
) -> SlimDocument:
    """Convert a SharePoint site page to a SlimDocument object."""
    page_id = site_page.get("id")
    if page_id is None:
        raise ValueError("Site page ID is required")

    external_access = get_sharepoint_external_access(
        ctx=ctx,  # ty: ignore[invalid-argument-type]
        graph_client=graph_client,
        permission_cache=permission_cache,
        site_page=site_page,
        treat_sharing_link_as_public=treat_sharing_link_as_public,
    )

    return SlimDocument(
        id=page_id,
        external_access=external_access,
        parent_hierarchy_raw_node_id=parent_hierarchy_raw_node_id,
        doc_created_at=parse_graph_datetime(site_page.get("createdDateTime")),
    )


class SharepointConnector(
    SlimConnector,
    SlimConnectorWithPermSync,
    CheckpointedConnectorWithPermSync[SharepointConnectorCheckpoint],
    Resolver,
):
    def __init__(
        self,
        batch_size: int = INDEX_BATCH_SIZE,
        sites: list[str] | None = None,
        excluded_sites: list[str] | None = None,
        excluded_paths: list[str] | None = None,
        include_site_pages: bool = True,
        include_site_documents: bool = True,
        treat_sharing_link_as_public: bool = False,
        authority_host: str = DEFAULT_AUTHORITY_HOST,
        graph_api_host: str = DEFAULT_GRAPH_API_HOST,
        sharepoint_domain_suffix: str = DEFAULT_SHAREPOINT_DOMAIN_SUFFIX,
    ) -> None:
        if excluded_paths is None:
            excluded_paths = []
        if excluded_sites is None:
            excluded_sites = []
        if sites is None:
            sites = []
        self.batch_size = batch_size
        self.sites = list(sites)
        self.excluded_sites = [s for p in excluded_sites if (s := p.strip())]
        self.excluded_paths = [s for p in excluded_paths if (s := p.strip())]
        self.treat_sharing_link_as_public = treat_sharing_link_as_public
        self.site_descriptors: list[SiteDescriptor] = self._extract_site_and_drive_info(
            sites
        )
        self._graph_client: GraphClient | None = None
        self.msal_app: msal.ConfidentialClientApplication | None = None
        self.auth_method: MicrosoftAuthMethod | None = None
        self.include_site_pages = include_site_pages
        self.include_site_documents = include_site_documents
        self.sp_tenant_domain: str | None = None
        self._credential_json: dict[str, Any] | None = None
        self._cached_rest_ctx: ClientContext | None = None
        self._cached_rest_ctx_url: str | None = None
        self._cached_rest_ctx_created_at: float = 0.0

        resolved_env = resolve_microsoft_environment(graph_api_host, authority_host)
        self._azure_environment = resolved_env.environment
        self.authority_host = resolved_env.authority_host
        self.graph_api_host = resolved_env.graph_host
        self.graph_api_base = f"{self.graph_api_host}/v1.0"
        self.sharepoint_domain_suffix = resolved_env.sharepoint_domain_suffix
        if sharepoint_domain_suffix != resolved_env.sharepoint_domain_suffix:
            logger.warning(
                "Configured sharepoint_domain_suffix '%s' differs from the expected suffix '%s' for the %s environment. Using '%s'.",
                sharepoint_domain_suffix,
                resolved_env.sharepoint_domain_suffix,
                resolved_env.environment,
                resolved_env.sharepoint_domain_suffix,
            )

    def validate_connector_settings(self) -> None:
        # Validate that at least one content type is enabled
        if not self.include_site_documents and not self.include_site_pages:
            raise ConnectorValidationError(
                "At least one content type must be enabled. "
                "Please check either 'Include Site Documents' or 'Include Site Pages' (or both)."
            )

        # Ensure sites are sharepoint urls
        for site_url in self.sites:
            if not site_url.startswith("https://") or not (
                "/sites/" in site_url
                or "/teams/" in site_url
                or "/personal/" in site_url
            ):
                raise ConnectorValidationError(
                    "Site URLs must be full Sharepoint/OneDrive URLs (e.g. https://your-tenant.sharepoint.com/sites/your-site, https://your-tenant.sharepoint.com/teams/your-team or https://your-tenant-my.sharepoint.com/personal/your-user)"
                )
            try:
                validate_outbound_http_url(site_url, https_only=True)
            except (SSRFException, ValueError) as e:
                raise ConnectorValidationError(
                    f"Invalid site URL '{site_url}': {e}"
                ) from e

    def probe_role_assignments_permission(self) -> None:
        """Verify the Azure AD app can read SharePoint RoleAssignments.

        Required for permission sync (RoleAssignments enumeration uses the
        SharePoint REST surface, which is granted separately from Graph and
        can be granted unevenly across sites under the Sites.Selected model).
        Probes up to the first ROLE_ASSIGNMENTS_PROBE_MAX_SITES configured
        sites in parallel and fails if any of them rejects the request, so
        per-site permission gaps surface at validation time rather than
        mid-index. Only runs when credentials have been loaded.
        """
        if not (self.msal_app and self.sp_tenant_domain and self.sites):
            return

        # SharePoint blocks app-only REST tokens that came from a client
        # secret, so no permission grant can make this credential work.
        if self.auth_method is MicrosoftAuthMethod.CLIENT_SECRET:
            raise ConnectorValidationError(
                "Permission sync needs the SharePoint REST API, which only accepts "
                "app-only tokens from certificate authentication. This credential "
                "uses a client secret, so SharePoint denies the request no matter "
                "which permissions are granted. Recreate the credential with "
                "Certificate Authentication, or turn permission sync off."
            )

        try:
            token_response = acquire_token_for_rest(
                self.msal_app,
                self.sp_tenant_domain,
                self.sharepoint_domain_suffix,
            )
        except Exception as e:
            logger.warning(
                "RoleAssignments permission probe failed (non-blocking): %s", e
            )
            return

        sites_to_probe = self.sites[:ROLE_ASSIGNMENTS_PROBE_MAX_SITES]
        headers = {"Authorization": f"Bearer {token_response.accessToken}"}
        results = run_functions_tuples_in_parallel(
            [
                (_probe_site_role_assignments_authorized, (site_url, headers))
                for site_url in sites_to_probe
            ],
            allow_failures=True,
        )
        unauthorized_sites: list[str] = [
            site_url
            for site_url, authorized in zip(sites_to_probe, results, strict=True)
            if authorized is False
        ]

        if not unauthorized_sites:
            return

        sites_summary = ", ".join(unauthorized_sites)
        raise ConnectorValidationError(
            "The Azure AD app registration is missing the required SharePoint permission "
            "to read role assignments on the following site(s): "
            f"{sites_summary}. Please grant 'Sites.FullControl.All' "
            "(application permission) in the Azure portal and re-run admin consent. "
            "If using the 'Sites.Selected' model, ensure the app has been explicitly "
            "granted full-control on each affected site collection."
        )

    def probe_group_members_permission(self) -> None:
        """Verify the Azure AD app can enumerate Azure AD group members via Graph.

        Required for permission sync, which expands Azure AD groups attached to
        SharePoint role assignments via `GET /v1.0/groups/{id}/members`. Tested
        via `GET /v1.0/groups?$top=1`, which requires the same permission set
        (GroupMember.Read.All / Group.Read.All / Directory.Read.All) so a 403
        here reliably predicts a 403 on the members call. Only runs when
        credentials have been loaded.
        """
        if not self.msal_app:
            return
        try:
            access_token = self._get_graph_access_token()
            probe_url = f"{self.graph_api_base}/groups"
            resp = requests.get(
                probe_url,
                headers={"Authorization": f"Bearer {access_token}"},
                params={"$top": "1", "$select": "id"},
                timeout=10,
            )
            if resp.status_code in (401, 403):
                raise ConnectorValidationError(
                    "The Azure AD app registration is missing the required Microsoft Graph "
                    "permission to enumerate Azure AD group members. Please grant "
                    "'GroupMember.Read.All' (application permission) in the Azure portal "
                    "and re-run admin consent."
                )
        except ConnectorValidationError:
            raise
        except Exception as e:
            logger.warning(
                "Group members permission probe failed (non-blocking): %s", e
            )

    def _extract_tenant_domain_from_sites(self) -> str | None:
        """Extract the tenant domain from configured site URLs.

        Site URLs look like https://{tenant}.sharepoint.com/sites/... so the
        tenant domain is the first label of the hostname.
        """
        for site_url in self.sites:
            try:
                hostname = urlsplit(site_url.strip()).hostname
            except ValueError:
                continue
            if not hostname:
                continue
            tenant = hostname.split(".")[0]
            if tenant:
                return tenant
        logger.warning("No tenant domain found from %s sites", len(self.sites))
        return None

    def _resolve_tenant_domain_from_root_site(self) -> str:
        """Resolve tenant domain via GET /v1.0/sites/root which only requires
        Sites.Read.All (a permission the connector already needs)."""
        root_site = self.graph_client.sites.root.get().execute_query()
        hostname = root_site.site_collection.hostname
        if not hostname:
            raise ConnectorValidationError(
                "Could not determine tenant domain from root site"
            )
        tenant_domain = hostname.split(".")[0]
        logger.info(
            "Resolved tenant domain '%s' from root site hostname '%s'",
            tenant_domain,
            hostname,
        )
        return tenant_domain

    def _resolve_tenant_domain(self) -> str:
        """Determine the tenant domain, preferring site URLs over a Graph API
        call to avoid needing extra permissions."""
        from_sites = self._extract_tenant_domain_from_sites()
        if from_sites:
            logger.info(
                "Resolved tenant domain '%s' from site URLs",
                from_sites,
            )
            return from_sites

        logger.info("No site URLs available; resolving tenant domain from root site")
        return self._resolve_tenant_domain_from_root_site()

    @property
    def graph_client(self) -> GraphClient:
        if self._graph_client is None:
            raise ConnectorMissingCredentialError("Sharepoint")

        return self._graph_client

    def _create_rest_client_context(self, site_url: str) -> ClientContext:
        """Return a ClientContext for SharePoint REST API calls, with caching.

        The office365 library's ClientContext caches the access token from its
        first request and never re-invokes the token callback.  We cache the
        context and recreate it when the site URL changes or after
        ``_REST_CTX_MAX_AGE_S``.  On recreation we also call
        ``load_credentials`` to build a fresh MSAL app with an empty token
        cache, guaranteeing a brand-new token from Azure AD."""
        elapsed = time.monotonic() - self._cached_rest_ctx_created_at
        if (
            self._cached_rest_ctx is not None
            and self._cached_rest_ctx_url == site_url
            and elapsed <= _REST_CTX_MAX_AGE_S
        ):
            return self._cached_rest_ctx

        if self._credential_json:
            logger.info(
                "Rebuilding SharePoint REST client context (elapsed=%.0fs, site_changed=%s)",
                elapsed,
                self._cached_rest_ctx_url != site_url,
            )
            self.load_credentials(self._credential_json)

        if not self.msal_app or not self.sp_tenant_domain:
            raise RuntimeError("MSAL app or tenant domain is not set")

        msal_app = self.msal_app
        sp_tenant_domain = self.sp_tenant_domain
        sp_domain_suffix = self.sharepoint_domain_suffix
        self._cached_rest_ctx = ClientContext(site_url).with_access_token(
            lambda: acquire_token_for_rest(msal_app, sp_tenant_domain, sp_domain_suffix)
        )
        self._cached_rest_ctx_url = site_url
        self._cached_rest_ctx_created_at = time.monotonic()
        return self._cached_rest_ctx

    @staticmethod
    def _strip_share_link_tokens(path: str) -> list[str]:
        # Share links often include a token prefix like /:f:/r/ or /:x:/r/.
        segments = [segment for segment in path.split("/") if segment]
        if segments and segments[0].startswith(":"):
            segments = segments[1:]
            if segments and segments[0] in {"r", "s", "g"}:
                segments = segments[1:]
        return segments

    @staticmethod
    def _normalize_sharepoint_url(url: str) -> tuple[str | None, list[str]]:
        try:
            parsed = urlsplit(url)
        except ValueError:
            logger.warning("Sharepoint URL '%s' could not be parsed", url)
            return None, []

        if not parsed.scheme or not parsed.netloc:
            logger.warning(
                "Sharepoint URL '%s' is not a valid absolute URL (missing scheme or host)",
                url,
            )
            return None, []

        path_segments = SharepointConnector._strip_share_link_tokens(parsed.path)
        return f"{parsed.scheme}://{parsed.netloc}", path_segments

    @staticmethod
    def _extract_site_and_drive_info(site_urls: list[str]) -> list[SiteDescriptor]:
        site_data_list = []
        for url in site_urls:
            base_url, parts = SharepointConnector._normalize_sharepoint_url(url.strip())
            if base_url is None:
                continue

            lower_parts = [part.lower() for part in parts]
            site_type_index = None
            for site_token in ("sites", "teams", "personal"):
                if site_token in lower_parts:
                    site_type_index = lower_parts.index(site_token)
                    break

            if site_type_index is None or len(parts) <= site_type_index + 1:
                logger.warning(
                    "Site URL '%s' is not a valid Sharepoint URL (must contain /sites/<name>, /teams/<name>, or /personal/<name>)",
                    url,
                )
                continue

            site_path = parts[: site_type_index + 2]
            remaining_parts = parts[site_type_index + 2 :]
            site_url = f"{base_url}/" + "/".join(site_path)

            # Extract drive name and folder path
            if remaining_parts:
                drive_name = unquote(remaining_parts[0])
                folder_path = (
                    "/".join(unquote(part) for part in remaining_parts[1:])
                    if len(remaining_parts) > 1
                    else None
                )
            else:
                drive_name = None
                folder_path = None

            site_data_list.append(
                SiteDescriptor(
                    url=site_url,
                    drive_name=drive_name,
                    folder_path=folder_path,
                )
            )
        return site_data_list

    def _resolve_drive(
        self,
        site_descriptor: SiteDescriptor,
        drive_name: str,
    ) -> tuple[str, str | None] | None:
        """Find the drive ID and web_url for a given drive name on a site.

        Returns (drive_id, drive_web_url) or None if the drive was not found.
        Raises on auth/permission errors so callers can propagate them.
        """
        site = self.graph_client.sites.get_by_url(site_descriptor.url)
        drives = site.drives.get().execute_query()
        logger.info("Found drives: %s", [d.name for d in drives])

        matched = [
            d
            for d in drives
            if (d.name and d.name.lower() == drive_name.lower())
            or (
                d.name in SHARED_DOCUMENTS_MAP
                and SHARED_DOCUMENTS_MAP[d.name] == drive_name
            )
        ]
        if not matched and drives:
            # Fallback for OneDrive personal sites: Graph reports the primary
            # library's name as "OneDrive"/"documentLibrary" while the
            # browser/SharePoint URL uses "Documents". Identify the intended
            # drive by its stable driveType (falling back to name), never by
            # position in the /drives response, whose order is not guaranteed.
            # Prefer driveType matches so a uniquely-typed primary drive is not
            # made ambiguous by an unrelated library sharing a fallback name;
            # only consult names when no drive has a primary type.
            type_matches = [
                d
                for d in drives
                if (d.drive_type or "").lower() in ONEDRIVE_PRIMARY_DRIVE_TYPES
            ]
            name_matches = [
                d for d in drives if d.name and d.name.lower() in ONEDRIVE_DRIVE_NAMES
            ]
            onedrive_matches = type_matches or name_matches
            if PERSONAL_SITE_URL_MARKER in site_descriptor.url.lower():
                # A personal site has exactly one user OneDrive; refuse to guess
                # when the lookup is ambiguous rather than index an arbitrary
                # library.
                if len(onedrive_matches) == 1:
                    matched = onedrive_matches
                elif len(onedrive_matches) > 1:
                    logger.warning(
                        "Could not unambiguously resolve the primary OneDrive "
                        "for personal site '%s' (%d candidate drives: %s)",
                        site_descriptor.url,
                        len(onedrive_matches),
                        [d.name for d in onedrive_matches],
                    )
            elif onedrive_matches:
                matched = [onedrive_matches[0]]

        if not matched:
            logger.warning("Drive '%s' not found", drive_name)
            return None

        drive = matched[0]
        drive_web_url: str | None = drive.web_url
        logger.info("Found drive: %s (web_url: %s)", drive.name, drive_web_url)
        return cast(str, drive.id), drive_web_url

    def _get_drive_items_for_drive_id(
        self,
        site_descriptor: SiteDescriptor,
        drive_id: str,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> Generator[DriveItemData, None, None]:
        """Yield drive items lazily for a given drive name.

        Uses the delta API for whole-drive enumeration (flat, incremental via
        timestamp token) and falls back to BFS /children traversal when a
        folder_path is configured, since delta cannot scope to a subtree
        efficiently.

        Returns:
            A generator of DriveItemData.
            The generator paginates through the Graph API so items are never
            all held in memory at once.
        """
        try:
            if site_descriptor.folder_path:
                yield from iter_drive_items_paged(
                    self.graph_api,
                    drive_id=drive_id,
                    folder_path=site_descriptor.folder_path,
                    start=start,
                    end=end,
                )
            else:
                yield from iter_drive_items_delta(
                    self.graph_api,
                    drive_id=drive_id,
                    start=start,
                    end=end,
                )

        except Exception as e:
            err_str = str(e)
            if (
                "403 Client Error" in err_str
                or "404 Client Error" in err_str
                or "invalid_client" in err_str
            ):
                raise e

            logger.warning(
                "Failed to process site: %s - %s", site_descriptor.url, err_str
            )

    def _fetch_driveitems(
        self,
        site_descriptor: SiteDescriptor,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> Generator[tuple[DriveItemData, str, str | None], None, None]:
        """Yield drive items lazily for all drives in a site.

        Yields (DriveItemData, drive_name, drive_web_url) tuples one item at
        a time, paginating through the Graph API internally.
        """
        try:
            site = self.graph_client.sites.get_by_url(site_descriptor.url)
            drives = site.drives.get().execute_query()
            logger.debug("Found drives: %s", [d.name for d in drives])

            if site_descriptor.drive_name:
                drives = [
                    drive
                    for drive in drives
                    if drive.name == site_descriptor.drive_name
                    or (
                        drive.name in SHARED_DOCUMENTS_MAP
                        and SHARED_DOCUMENTS_MAP[drive.name]
                        == site_descriptor.drive_name
                    )
                ]
                if not drives:
                    logger.warning("Drive '%s' not found", site_descriptor.drive_name)
                    return

            for drive in drives:
                try:
                    drive_name = (
                        SHARED_DOCUMENTS_MAP[drive.name]
                        if drive.name in SHARED_DOCUMENTS_MAP
                        else cast(str, drive.name)
                    )
                    drive_web_url: str | None = drive.web_url

                    if site_descriptor.folder_path:
                        item_iter = iter_drive_items_paged(
                            self.graph_api,
                            drive_id=cast(str, drive.id),
                            folder_path=site_descriptor.folder_path,
                            start=start,
                            end=end,
                        )
                    else:
                        item_iter = iter_drive_items_delta(
                            self.graph_api,
                            drive_id=cast(str, drive.id),
                            start=start,
                            end=end,
                        )

                    for item in item_iter:
                        yield item, drive_name or "", drive_web_url

                except Exception as e:
                    logger.warning(
                        "Failed to process drive '%s': %s", drive.name, str(e)
                    )

        except Exception as e:
            err_str = str(e)
            if (
                "403 Client Error" in err_str
                or "404 Client Error" in err_str
                or "invalid_client" in err_str
            ):
                raise e

            logger.warning("Failed to process site: %s", err_str)

    def _handle_paginated_sites(
        self, sites: SitesWithRoot
    ) -> Generator[Site, None, None]:
        while sites:
            if sites.current_page:
                yield from sites.current_page
            if not sites.has_next:
                break
            sites = sites._get_next().execute_query()

    def _is_driveitem_excluded(self, driveitem: DriveItemData) -> bool:
        """Check if a drive item should be excluded based on excluded_paths patterns."""
        if not self.excluded_paths:
            return False
        relative_path = build_item_relative_path(
            driveitem.parent_reference_path, driveitem.name
        )
        return is_path_excluded(relative_path, self.excluded_paths)

    def _filter_excluded_sites(
        self, site_descriptors: list[SiteDescriptor]
    ) -> list[SiteDescriptor]:
        """Remove sites matching any excluded_sites glob pattern."""
        if not self.excluded_sites:
            return site_descriptors
        result = []
        for sd in site_descriptors:
            if _is_site_excluded(sd.url, self.excluded_sites):
                logger.info("Excluding site by denylist: %s", sd.url)
                continue
            result.append(sd)
        return result

    def fetch_sites(self) -> list[SiteDescriptor]:
        sites = self.graph_client.sites.get_all_sites().execute_query()

        if not sites:
            raise RuntimeError("No sites found in the tenant")

        # OneDrive personal sites should not be indexed with SharepointConnector
        site_descriptors = [
            SiteDescriptor(
                url=site.web_url or "",
                drive_name=None,
                folder_path=None,
            )
            for site in self._handle_paginated_sites(sites)
            if "-my.sharepoint" not in site.web_url
        ]
        return self._filter_excluded_sites(site_descriptors)

    def _fetch_site_pages(
        self,
        site_descriptor: SiteDescriptor,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> Generator[dict[str, Any], None, None]:
        """Yield SharePoint site pages (.aspx files) one at a time.

        Pages are fetched via the Graph Pages API and yielded lazily as each
        API page arrives, so memory stays bounded regardless of total page count.
        Time-window filtering is applied per-item before yielding.
        """
        site = self.graph_client.sites.get_by_url(site_descriptor.url)
        site.execute_query()
        site_id = site.id

        site_pages_base = (
            f"{self.graph_api_base}/sites/{site_id}/pages/microsoft.graph.sitePage"
        )
        page_url: str | None = site_pages_base
        params: dict[str, str] | None = {"$expand": "canvasLayout"}
        total_yielded = 0
        yielded_ids: set[str] = set()

        while page_url:
            try:
                data = self.graph_api.get_json(page_url, params)
            except HTTPError as e:
                if e.response is not None and e.response.status_code == 404:
                    logger.warning("Site page not found: %s", page_url)
                    break
                if (
                    e.response is not None
                    and e.response.status_code == 400
                    and _is_graph_invalid_request(e.response)
                ):
                    logger.warning(
                        "$expand=canvasLayout on the LIST endpoint returned 400 for site %s. Falling back to per-page expansion.",
                        site_descriptor.url,
                    )
                    yield from self._fetch_site_pages_individually(
                        site_pages_base, start, end, skip_ids=yielded_ids
                    )
                    return
                raise

            params = None  # nextLink already embeds query params

            for page in data.get("value", []):
                if not _site_page_in_time_window(page, start, end):
                    continue
                total_yielded += 1
                page_id = page.get("id")
                if page_id:
                    yielded_ids.add(page_id)
                yield page

            page_url = data.get("@odata.nextLink")

        logger.debug("Yielded %s site pages for %s", total_yielded, site_descriptor.url)

    def _fetch_site_pages_individually(
        self,
        site_pages_base: str,
        start: datetime | None = None,
        end: datetime | None = None,
        skip_ids: set[str] | None = None,
    ) -> Generator[dict[str, Any], None, None]:
        """Fallback for _fetch_site_pages: list pages without $expand, then
        expand canvasLayout on each page individually.

        The Graph API's LIST endpoint can return 400 when $expand=canvasLayout
        is used and *any* page in the site has a corrupt canvas layout (e.g.
        duplicate web part IDs — see SharePoint/sp-dev-docs#8822). Since the
        LIST expansion is all-or-nothing, a single bad page poisons the entire
        response. This method works around it by fetching metadata first, then
        expanding each page individually so only the broken page loses its
        canvas content.

        ``skip_ids`` contains page IDs already yielded by the caller before the
        fallback was triggered, preventing duplicates.
        """
        page_url: str | None = site_pages_base
        total_yielded = 0
        _skip_ids = skip_ids or set()

        while page_url:
            try:
                data = self.graph_api.get_json(page_url)
            except HTTPError as e:
                if e.response is not None and e.response.status_code == 404:
                    break
                raise

            for page in data.get("value", []):
                if not _site_page_in_time_window(page, start, end):
                    continue

                page_id = page.get("id")
                if page_id and page_id in _skip_ids:
                    continue

                if not page_id:
                    total_yielded += 1
                    yield page
                    continue

                expanded = self._try_expand_single_page(site_pages_base, page_id, page)
                total_yielded += 1
                yield expanded

            page_url = data.get("@odata.nextLink")

        logger.debug(
            "Yielded %s site pages (per-page expansion fallback)", total_yielded
        )

    def _try_expand_single_page(
        self,
        site_pages_base: str,
        page_id: str,
        fallback_page: dict[str, Any],
    ) -> dict[str, Any]:
        """Try to GET a single page with $expand=canvasLayout. On 400, return
        the metadata-only fallback so the page is still indexed (without canvas
        content)."""
        pages_collection = site_pages_base.removesuffix("/microsoft.graph.sitePage")
        single_url = f"{pages_collection}/{page_id}/microsoft.graph.sitePage"
        try:
            return self.graph_api.get_json(single_url, {"$expand": "canvasLayout"})
        except HTTPError as e:
            if (
                e.response is not None
                and e.response.status_code == 400
                and _is_graph_invalid_request(e.response)
            ):
                page_name = fallback_page.get("name", page_id)
                logger.warning(
                    "$expand=canvasLayout failed for page '%s' (%s). Indexing metadata only.",
                    page_name,
                    page_id,
                )
                return fallback_page
            raise

    def _fetch_single_site_page(self, site_id: str, page_id: str) -> dict[str, Any]:
        """Fetch one site page by id with canvasLayout expanded.

        Fetches metadata first so ``_try_expand_single_page`` has a valid
        fallback if expansion 400s on a corrupt page. Mirrors a single iteration
        of ``_fetch_site_pages`` for the targeted-reindex path.
        """
        pages_collection = f"{self.graph_api_base}/sites/{site_id}/pages"
        site_pages_base = f"{pages_collection}/microsoft.graph.sitePage"
        metadata = self.graph_api.get_json(
            f"{pages_collection}/{page_id}/microsoft.graph.sitePage"
        )
        return self._try_expand_single_page(site_pages_base, page_id, metadata)

    def _acquire_token(self) -> dict[str, Any]:
        """
        Acquire token via MSAL
        """
        if self.msal_app is None:
            raise RuntimeError("MSAL app is not initialized")

        return acquire_graph_token(self.msal_app, self.graph_api_host)

    def _get_graph_access_token(self) -> str:
        token_data = self._acquire_token()
        access_token = token_data.get("access_token")
        if not access_token:
            raise RuntimeError("Failed to acquire Graph API access token")
        return access_token

    @property
    def graph_api(self) -> GraphApiClient:
        """The raw Graph REST surface, bound to this connector's token source."""
        return GraphApiClient(self._get_graph_access_token, self.graph_api_base)

    @staticmethod
    def _clear_drive_checkpoint_state(
        checkpoint: "SharepointConnectorCheckpoint",
    ) -> None:
        """Reset all drive-level fields in the checkpoint."""
        checkpoint.current_drive_name = None
        checkpoint.current_drive_id = None
        checkpoint.current_drive_web_url = None
        checkpoint.current_drive_delta_next_link = None
        checkpoint.seen_document_ids.clear()

    def _fetch_slim_documents_from_sharepoint(
        self,
        start: datetime | None = None,
        end: datetime | None = None,
        include_permissions: bool = True,
    ) -> GenerateSlimDocumentOutput:
        site_descriptors = self._filter_excluded_sites(
            self.site_descriptors or self.fetch_sites()
        )

        # Create a temporary checkpoint for hierarchy node tracking
        temp_checkpoint = SharepointConnectorCheckpoint(has_more=True)

        # goes over all urls, converts them into SlimDocument objects and then yields them in batches
        doc_batch: list[SlimDocument | HierarchyNode] = []
        for site_descriptor in site_descriptors:
            site_url = site_descriptor.url

            # Yield site hierarchy node using helper
            doc_batch.extend(
                self._yield_site_hierarchy_node(
                    site_descriptor,
                    temp_checkpoint,
                    include_permissions=include_permissions,
                )
            )

            # Process site documents if flag is True
            if self.include_site_documents:
                for driveitem, drive_name, drive_web_url in self._fetch_driveitems(
                    site_descriptor=site_descriptor,
                    start=start,
                    end=end,
                ):
                    if self._is_driveitem_excluded(driveitem):
                        logger.debug(
                            "Excluding by path denylist: %s", driveitem.web_url
                        )
                        continue

                    if drive_web_url:
                        doc_batch.extend(
                            self._yield_drive_hierarchy_node(
                                site_url,
                                drive_web_url,
                                drive_name,
                                temp_checkpoint,
                                include_permissions=include_permissions,
                            )
                        )

                    folder_path = extract_folder_path_from_parent_reference(
                        driveitem.parent_reference_path
                    )
                    if folder_path and drive_web_url:
                        doc_batch.extend(
                            self._yield_folder_hierarchy_nodes(
                                site_url,
                                drive_web_url,
                                drive_name,
                                folder_path,
                                temp_checkpoint,
                                include_permissions=include_permissions,
                            )
                        )

                    parent_hierarchy_url: str | None = None
                    if drive_web_url:
                        parent_hierarchy_url = self._get_parent_hierarchy_url(
                            site_url, drive_web_url, drive_name, driveitem
                        )

                    try:
                        logger.debug("Processing: %s", driveitem.web_url)
                        if include_permissions:
                            ctx = self._create_rest_client_context(site_descriptor.url)
                            doc_batch.append(
                                _convert_driveitem_to_slim_document(
                                    driveitem,
                                    drive_name,
                                    ctx,
                                    self.graph_client,
                                    temp_checkpoint.permission_cache,
                                    parent_hierarchy_raw_node_id=parent_hierarchy_url,
                                    treat_sharing_link_as_public=self.treat_sharing_link_as_public,
                                )
                            )
                        else:
                            if driveitem.id is None:
                                raise ValueError("DriveItem ID is required")
                            doc_batch.append(
                                SlimDocument(
                                    id=driveitem.id,
                                    external_access=ExternalAccess.empty(),
                                    parent_hierarchy_raw_node_id=parent_hierarchy_url,
                                    doc_created_at=driveitem.created_datetime,
                                )
                            )
                    except Exception as e:
                        logger.warning("Failed to process driveitem: %s", str(e))

                    if len(doc_batch) >= SLIM_BATCH_SIZE:
                        yield doc_batch
                        doc_batch = []

            # Process site pages if flag is True
            if self.include_site_pages:
                try:
                    site_pages = self._fetch_site_pages(
                        site_descriptor, start=start, end=end
                    )
                    for site_page in site_pages:
                        logger.debug(
                            "Processing site page: %s",
                            site_page.get("webUrl", site_page.get("name", "Unknown")),
                        )
                        try:
                            if include_permissions:
                                ctx = self._create_rest_client_context(
                                    site_descriptor.url
                                )
                                doc_batch.append(
                                    _convert_sitepage_to_slim_document(
                                        site_page,
                                        ctx,
                                        self.graph_client,
                                        temp_checkpoint.permission_cache,
                                        parent_hierarchy_raw_node_id=site_descriptor.url,
                                        treat_sharing_link_as_public=self.treat_sharing_link_as_public,
                                    )
                                )
                            else:
                                page_id = site_page.get("id")
                                if page_id is None:
                                    raise ValueError("Site page ID is required")
                                doc_batch.append(
                                    SlimDocument(
                                        id=page_id,
                                        external_access=ExternalAccess.empty(),
                                        parent_hierarchy_raw_node_id=site_descriptor.url,
                                        doc_created_at=parse_graph_datetime(
                                            site_page.get("createdDateTime")
                                        ),
                                    )
                                )
                        except Exception as e:
                            logger.warning(
                                "Failed to process site page %s: %s",
                                site_page.get(
                                    "webUrl", site_page.get("name", "Unknown")
                                ),
                                e,
                            )
                        if len(doc_batch) >= SLIM_BATCH_SIZE:
                            yield doc_batch
                            doc_batch = []
                except Exception as e:
                    # Broadened from per-site Graph 4xx to any Exception.
                    # Slim retrieval can't yield ConnectorFailure, so
                    # log-and-skip to keep perm sync alive for other sites.
                    if (
                        isinstance(e, (ClientRequestException, HTTPError))
                        and e.response is not None
                    ):
                        logger.warning(
                            "Skipping slim site pages for %s: Graph returned %s (%s)",
                            site_descriptor.url,
                            e.response.status_code,
                            graph_error_code(e.response),
                            exc_info=True,
                        )
                    else:
                        logger.warning(
                            "Skipping slim site pages for %s: %s",
                            site_descriptor.url,
                            e,
                            exc_info=True,
                        )
        yield doc_batch

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        self._credential_json = credentials
        auth_method = credentials.get(
            "authentication_method", MicrosoftAuthMethod.CLIENT_SECRET.value
        )
        sp_client_id = credentials.get("sp_client_id")
        sp_directory_id = credentials.get("sp_directory_id")
        if not sp_client_id:
            raise ConnectorValidationError("Client ID is required")
        if not sp_directory_id:
            raise ConnectorValidationError("Directory (tenant) ID is required")

        auth = build_msal_app(
            client_id=sp_client_id,
            directory_id=sp_directory_id,
            authority_host=self.authority_host,
            auth_method=auth_method,
            client_secret=credentials.get("sp_client_secret"),
            private_key_b64=credentials.get("sp_private_key"),
            certificate_password=credentials.get("sp_certificate_password"),
        )
        self.msal_app = auth.app
        self.auth_method = auth.method

        def _acquire_token_for_graph() -> dict[str, Any]:
            """
            Acquire token via MSAL
            """
            if self.msal_app is None:
                raise ConnectorValidationError("MSAL app is not initialized")

            token = acquire_graph_token(self.msal_app, self.graph_api_host)
            if token is None:
                raise ConnectorValidationError("Failed to acquire token for graph")
            return token

        self._graph_client = GraphClient(
            _acquire_token_for_graph, environment=self._azure_environment
        )
        self.sp_tenant_domain = self._resolve_tenant_domain()
        return None

    def _get_drive_names_for_site(self, site_url: str) -> list[str]:
        """Return all library/drive names for a given SharePoint site."""
        try:
            site = self.graph_client.sites.get_by_url(site_url)
            drives = site.drives.get_all(page_loaded=lambda _: None).execute_query()
            drive_names: list[str] = []
            for drive in drives:
                if drive.name is None:
                    continue
                drive_names.append(drive.name)

            return drive_names
        except Exception as e:
            logger.warning("Failed to fetch drives for site '%s': %s", site_url, e)
            return []

    def _build_folder_url(
        self, site_url: str, drive_name: str, folder_path: str
    ) -> str:
        """Build a URL for a folder to use as raw_node_id.

        NOTE: This constructs an approximate folder URL from components rather than
        fetching the actual webUrl from the API. The constructed URL may differ
        slightly from SharePoint's canonical webUrl (e.g., URL encoding differences),
        but it functions correctly as a unique identifier for hierarchy tracking.
        We avoid fetching folder metadata to minimize API calls.
        """
        return f"{site_url}/{drive_name}/{folder_path}"

    def _yield_site_hierarchy_node(
        self,
        site_descriptor: SiteDescriptor,
        checkpoint: SharepointConnectorCheckpoint,
        include_permissions: bool = False,
    ) -> Generator[HierarchyNode, None, None]:
        """Yield a hierarchy node for a site if not already yielded.

        Uses site.web_url as the raw_node_id (exact URL from API).
        """
        site_url = site_descriptor.url

        if site_url in checkpoint.seen_hierarchy_node_raw_ids:
            return

        checkpoint.seen_hierarchy_node_raw_ids.add(site_url)

        # Extract display name from URL (last path segment)
        display_name = site_url.rstrip("/").split("/")[-1]
        external_access = None
        if include_permissions:
            ctx = self._create_rest_client_context(site_url)
            external_access = get_sharepoint_hierarchy_node_external_access(
                ctx,
                self.graph_client,
                checkpoint.permission_cache,
                HierarchyNodeType.SITE,
            )

        yield HierarchyNode(
            raw_node_id=site_url,
            raw_parent_id=None,  # Parent is SOURCE
            display_name=display_name,
            link=site_url,
            node_type=HierarchyNodeType.SITE,
            external_access=external_access,
        )

    def _yield_drive_hierarchy_node(
        self,
        site_url: str,
        drive_web_url: str,
        drive_name: str,
        checkpoint: SharepointConnectorCheckpoint,
        include_permissions: bool = False,
    ) -> Generator[HierarchyNode, None, None]:
        """Yield a hierarchy node for a drive if not already yielded.

        Uses drive.web_url as the raw_node_id (exact URL from API).
        """
        if drive_web_url in checkpoint.seen_hierarchy_node_raw_ids:
            return

        checkpoint.seen_hierarchy_node_raw_ids.add(drive_web_url)
        external_access = None
        if include_permissions:
            ctx = self._create_rest_client_context(site_url)
            external_access = get_sharepoint_hierarchy_node_external_access(
                ctx,
                self.graph_client,
                checkpoint.permission_cache,
                HierarchyNodeType.DRIVE,
                drive_name=drive_name,
            )

        yield HierarchyNode(
            raw_node_id=drive_web_url,
            raw_parent_id=site_url,  # Site URL is parent
            display_name=drive_name,
            link=drive_web_url,
            node_type=HierarchyNodeType.DRIVE,
            external_access=external_access,
        )

    def _yield_folder_hierarchy_nodes(
        self,
        site_url: str,
        drive_web_url: str,
        drive_name: str,
        folder_path: str,
        checkpoint: SharepointConnectorCheckpoint,
        include_permissions: bool = False,
    ) -> Generator[HierarchyNode, None, None]:
        """Yield hierarchy nodes for all folders in a path.

        For path "Engineering/API/v2", yields nodes for:
        1. "Engineering" (parent = drive)
        2. "Engineering/API" (parent = "Engineering")
        3. "Engineering/API/v2" (parent = "Engineering/API")

        Nodes are yielded in parent-to-child order.

        Uses constructed URLs as raw_node_id. See _build_folder_url for details
        on why we construct URLs rather than fetching them from the API.
        """
        if not folder_path:
            return

        path_parts = folder_path.split("/")

        for i, part in enumerate(path_parts):
            current_path = "/".join(path_parts[: i + 1])
            folder_url = self._build_folder_url(site_url, drive_name, current_path)

            if folder_url in checkpoint.seen_hierarchy_node_raw_ids:
                continue

            checkpoint.seen_hierarchy_node_raw_ids.add(folder_url)
            external_access = None
            if include_permissions:
                ctx = self._create_rest_client_context(site_url)
                external_access = get_sharepoint_hierarchy_node_external_access(
                    ctx,
                    self.graph_client,
                    checkpoint.permission_cache,
                    HierarchyNodeType.FOLDER,
                    folder_url=folder_url,
                )

            # Determine parent URL
            if i == 0:
                # First folder, parent is the drive
                parent_url = drive_web_url
            else:
                # Parent is the previous folder
                parent_path = "/".join(path_parts[:i])
                parent_url = self._build_folder_url(site_url, drive_name, parent_path)

            yield HierarchyNode(
                raw_node_id=folder_url,
                raw_parent_id=parent_url,
                display_name=part,  # Just the folder name
                link=folder_url,
                node_type=HierarchyNodeType.FOLDER,
                external_access=external_access,
            )

    def _get_parent_hierarchy_url(
        self,
        site_url: str,
        drive_web_url: str,
        drive_name: str,
        driveitem: DriveItemData,
    ) -> str:
        """Determine the parent hierarchy node URL for a document.

        Returns:
            - Folder URL if document is in a folder
            - Drive URL if document is at drive root
        """
        folder_path = extract_folder_path_from_parent_reference(
            driveitem.parent_reference_path
        )

        if folder_path:
            return self._build_folder_url(site_url, drive_name, folder_path)

        # Document is at drive root
        return drive_web_url

    def _process_drive_item(
        self,
        driveitem: DriveItemData,
        drive_name: str,
        drive_web_url: str | None,
        site_url: str,
        checkpoint: SharepointConnectorCheckpoint,
        include_permissions: bool,
        is_targeted_reindex: bool = False,
    ) -> Generator[Document | ConnectorFailure | HierarchyNode, None, None]:
        """Process a single drive item into a Document (plus ancestor folder
        nodes), or a ConnectorFailure on error.

        Shared by the normal crawl (Phase 3b) and the targeted-reindex
        ``reindex`` path. ``checkpoint`` is used purely as a dedup container
        (``seen_document_ids`` / ``seen_hierarchy_node_raw_ids``); reindex passes
        a throwaway checkpoint.

        When ``is_targeted_reindex`` is True, the branches that the crawl skips
        silently (denylist, unsupported type, empty non-PDF/image, non-indexable
        conversion) instead yield an informative ConnectorFailure: the admin
        explicitly requested the document, so it must end as a Document or a
        ConnectorFailure rather than silently reporting as still-failing with the
        stale original message. The duplicate-skip stays silent in both paths —
        a duplicate target has already been yielded as a Document in this call,
        so failing it would wrongly mark a landed doc as failed.
        """
        if self._is_driveitem_excluded(driveitem):
            logger.debug("Excluding by path denylist: %s", driveitem.web_url)
            if is_targeted_reindex:
                yield _create_document_failure(driveitem, "excluded by path denylist")
            return

        if driveitem.id and driveitem.id in checkpoint.seen_document_ids:
            logger.debug(
                "Skipping duplicate document %s (%s)",
                driveitem.id,
                driveitem.name,
            )
            return

        driveitem_extension = get_file_ext(driveitem.name)
        if driveitem_extension not in OnyxFileExtensions.ALL_ALLOWED_EXTENSIONS:
            logger.warning(
                "Skipping %s as it is not a supported file type",
                driveitem.web_url,
            )
            if is_targeted_reindex:
                yield _create_document_failure(
                    driveitem,
                    f"unsupported file type '{driveitem_extension}'",
                )
            return

        should_yield_if_empty = (
            driveitem_extension in OnyxFileExtensions.IMAGE_EXTENSIONS
            or driveitem_extension == ".pdf"
        )

        folder_path = extract_folder_path_from_parent_reference(
            driveitem.parent_reference_path
        )
        if folder_path and drive_web_url:
            yield from self._yield_folder_hierarchy_nodes(
                site_url,
                drive_web_url,
                drive_name,
                folder_path,
                checkpoint,
                include_permissions=include_permissions,
            )

        parent_hierarchy_url: str | None = None
        if drive_web_url:
            parent_hierarchy_url = self._get_parent_hierarchy_url(
                site_url,
                drive_web_url,
                drive_name,
                driveitem,
            )

        try:
            ctx: ClientContext | None = None
            if include_permissions:
                ctx = self._create_rest_client_context(site_url)

            access_token = self._get_graph_access_token()
            doc_or_failure = _convert_driveitem_to_document_with_permissions(
                driveitem,
                drive_name,
                ctx,
                self.graph_client,
                permission_cache=checkpoint.permission_cache,
                include_permissions=include_permissions,
                parent_hierarchy_raw_node_id=parent_hierarchy_url,
                graph_api_base=self.graph_api_base,
                access_token=access_token,
                treat_sharing_link_as_public=self.treat_sharing_link_as_public,
                raw_file_callback=self.raw_file_callback,
            )

            if isinstance(doc_or_failure, Document):
                if doc_or_failure.sections:
                    checkpoint.seen_document_ids.add(doc_or_failure.id)
                    yield doc_or_failure
                elif should_yield_if_empty:
                    doc_or_failure.sections = [
                        TextSection(link=driveitem.web_url, text="")
                    ]
                    checkpoint.seen_document_ids.add(doc_or_failure.id)
                    yield doc_or_failure
                else:
                    logger.warning(
                        "Skipping %s as it is empty and not a PDF or image",
                        driveitem.web_url,
                    )
                    if is_targeted_reindex:
                        yield _create_document_failure(
                            driveitem, "document is empty and not a PDF or image"
                        )
            elif isinstance(doc_or_failure, ConnectorFailure):
                yield doc_or_failure
            elif is_targeted_reindex:
                # Converter returned None: excluded/malformed content type or
                # over the size threshold (it logs the specifics).
                yield _create_document_failure(
                    driveitem,
                    "not indexable (excluded content type or over size limit)",
                )
        except Exception as e:
            logger.warning(
                "Failed to process driveitem %s: %s",
                driveitem.web_url,
                e,
            )
            yield _create_document_failure(driveitem, f"Failed to process: {str(e)}", e)

    def _load_from_checkpoint(
        self,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
        checkpoint: SharepointConnectorCheckpoint,
        include_permissions: bool = False,
    ) -> CheckpointOutput[SharepointConnectorCheckpoint]:
        if self._graph_client is None:
            raise ConnectorMissingCredentialError("Sharepoint")

        checkpoint = copy.deepcopy(checkpoint)

        # Phase 1: Initialize cached_site_descriptors if needed
        if (
            checkpoint.has_more
            and checkpoint.cached_site_descriptors is None
            and not checkpoint.process_site_pages
        ):
            logger.info("Initializing SharePoint sites for processing")
            site_descs = self._filter_excluded_sites(
                self.site_descriptors or self.fetch_sites()
            )
            checkpoint.cached_site_descriptors = deque(site_descs)

            if not checkpoint.cached_site_descriptors:
                logger.warning(
                    "No SharePoint sites found or accessible - nothing to process"
                )
                checkpoint.has_more = False
                return checkpoint

            logger.info(
                "Found %s sites to process", len(checkpoint.cached_site_descriptors)
            )
            # Set first site and return to allow checkpoint persistence
            if checkpoint.cached_site_descriptors:
                checkpoint.current_site_descriptor = (
                    checkpoint.cached_site_descriptors.popleft()
                )
                logger.info(
                    "Starting with site: %s", checkpoint.current_site_descriptor.url
                )
                # Yield site hierarchy node for the first site
                yield from self._yield_site_hierarchy_node(
                    checkpoint.current_site_descriptor,
                    checkpoint,
                    include_permissions=include_permissions,
                )
                return checkpoint

        # Phase 2: Initialize cached_drive_names for current site if needed
        if checkpoint.current_site_descriptor and checkpoint.cached_drive_names is None:
            # If site documents flag is False, set empty drive list to skip document processing
            if not self.include_site_documents:
                logger.debug("Documents disabled, skipping drive initialization")
                checkpoint.cached_drive_names = deque()
                return checkpoint

            logger.info(
                "Initializing drives for site: %s",
                checkpoint.current_site_descriptor.url,
            )

            try:
                # If the user explicitly specified drive(s) for this site, honour that
                if checkpoint.current_site_descriptor.drive_name:
                    logger.info(
                        "Using explicitly specified drive: %s",
                        checkpoint.current_site_descriptor.drive_name,
                    )
                    checkpoint.cached_drive_names = deque(
                        [checkpoint.current_site_descriptor.drive_name]
                    )
                else:
                    drive_names = self._get_drive_names_for_site(
                        checkpoint.current_site_descriptor.url
                    )
                    checkpoint.cached_drive_names = deque(drive_names)

                if not checkpoint.cached_drive_names:
                    logger.warning(
                        "No accessible drives found for site: %s",
                        checkpoint.current_site_descriptor.url,
                    )
                else:
                    logger.info(
                        "Found %s drives: %s",
                        len(checkpoint.cached_drive_names),
                        list(checkpoint.cached_drive_names),
                    )

            except Exception as e:
                logger.error(
                    "Failed to initialize drives for site: %s: %s",
                    checkpoint.current_site_descriptor.url,
                    e,
                )
                # Yield a ConnectorFailure for site-level access failures
                start_dt = datetime.fromtimestamp(start, tz=timezone.utc)
                end_dt = datetime.fromtimestamp(end, tz=timezone.utc)
                yield _create_entity_failure(
                    checkpoint.current_site_descriptor.url,
                    f"Failed to access site: {str(e)}",
                    (start_dt, end_dt),
                    e,
                )
                # Move to next site if available
                if (
                    checkpoint.cached_site_descriptors
                    and len(checkpoint.cached_site_descriptors) > 0
                ):
                    checkpoint.current_site_descriptor = (
                        checkpoint.cached_site_descriptors.popleft()
                    )
                    checkpoint.cached_drive_names = None  # Reset for new site
                    return checkpoint
                else:
                    # No more sites - we're done
                    checkpoint.has_more = False
                    return checkpoint

            # Return checkpoint to allow persistence after drive initialization
            return checkpoint

        # Phase 3a: Initialize the next drive for processing
        if (
            checkpoint.current_site_descriptor
            and checkpoint.cached_drive_names
            and len(checkpoint.cached_drive_names) > 0
            and checkpoint.current_drive_name is None
        ):
            checkpoint.current_drive_name = checkpoint.cached_drive_names.popleft()

            start_dt = datetime.fromtimestamp(start, tz=timezone.utc)
            end_dt = datetime.fromtimestamp(end, tz=timezone.utc)
            site_descriptor = checkpoint.current_site_descriptor

            logger.info(
                "Processing drive '%s' in site: %s",
                checkpoint.current_drive_name,
                site_descriptor.url,
            )
            logger.debug("Time range: %s to %s", start_dt, end_dt)

            current_drive_name = checkpoint.current_drive_name
            if current_drive_name is None:
                logger.warning("Current drive name is None, skipping")
                return checkpoint

            try:
                logger.info(
                    "Fetching drive items for drive name: %s", current_drive_name
                )
                result = self._resolve_drive(site_descriptor, current_drive_name)
                if result is None:
                    logger.warning("Drive '%s' not found, skipping", current_drive_name)
                    self._clear_drive_checkpoint_state(checkpoint)
                    return checkpoint

                drive_id, drive_web_url = result
                checkpoint.current_drive_id = drive_id
                checkpoint.current_drive_web_url = drive_web_url
            except Exception as e:
                logger.error(
                    "Failed to retrieve items from drive '%s' in site: %s: %s",
                    current_drive_name,
                    site_descriptor.url,
                    e,
                )
                yield _create_entity_failure(
                    f"{site_descriptor.url}|{current_drive_name}",
                    f"Failed to access drive '{current_drive_name}' in site '{site_descriptor.url}': {str(e)}",
                    (start_dt, end_dt),
                    e,
                )
                self._clear_drive_checkpoint_state(checkpoint)
                return checkpoint

            display_drive_name = SHARED_DOCUMENTS_MAP.get(
                current_drive_name, current_drive_name
            )

            if drive_web_url:
                yield from self._yield_drive_hierarchy_node(
                    site_descriptor.url,
                    drive_web_url,
                    display_drive_name,
                    checkpoint,
                    include_permissions=include_permissions,
                )

            # For non-folder-scoped drives, use delta API with per-page
            # checkpointing.  Build the initial URL and fall through to 3b.
            if not site_descriptor.folder_path:
                checkpoint.current_drive_delta_next_link = build_delta_start_url(
                    self.graph_api_base, drive_id, start_dt
                )
            # else: BFS path, delta_next_link stays None and
            # Phase 3b walks with iter_drive_items_paged.

        # Phase 3b: Process items from the current drive
        if (
            checkpoint.current_site_descriptor
            and checkpoint.current_drive_name is not None
            and checkpoint.current_drive_id is not None
        ):
            site_descriptor = checkpoint.current_site_descriptor
            start_dt = datetime.fromtimestamp(start, tz=timezone.utc)
            end_dt = datetime.fromtimestamp(end, tz=timezone.utc)
            current_drive_name = SHARED_DOCUMENTS_MAP.get(
                checkpoint.current_drive_name, checkpoint.current_drive_name
            )
            drive_web_url = checkpoint.current_drive_web_url

            # --- determine item source ---
            driveitems: Iterable[DriveItemData]
            has_more_delta_pages = False

            if checkpoint.current_drive_delta_next_link:
                # Delta path: fetch one page at a time for checkpointing
                try:
                    page_items, next_url = fetch_one_delta_page(
                        self.graph_api,
                        page_url=checkpoint.current_drive_delta_next_link,
                        drive_id=checkpoint.current_drive_id,
                        start=start_dt,
                        end=end_dt,
                    )
                except Exception as e:
                    logger.error(
                        "Failed to fetch delta page for drive '%s': %s",
                        current_drive_name,
                        e,
                    )
                    yield _create_entity_failure(
                        f"{site_descriptor.url}|{current_drive_name}",
                        f"Failed to fetch delta page for drive '{current_drive_name}': {str(e)}",
                        (start_dt, end_dt),
                        e,
                    )
                    self._clear_drive_checkpoint_state(checkpoint)
                    return checkpoint

                driveitems = page_items
                has_more_delta_pages = next_url is not None
                if next_url:
                    checkpoint.current_drive_delta_next_link = next_url
            else:
                # BFS path (folder-scoped): process all items at once
                driveitems = iter_drive_items_paged(
                    self.graph_api,
                    drive_id=checkpoint.current_drive_id,
                    folder_path=site_descriptor.folder_path,
                    start=start_dt,
                    end=end_dt,
                )

            item_count = 0
            # Outer try catches BFS-generator failures mid-iteration;
            # per-item errors are still caught by the inner try below.
            try:
                for driveitem in driveitems:
                    item_count += 1
                    yield from self._process_drive_item(
                        driveitem,
                        current_drive_name,
                        drive_web_url,
                        site_descriptor.url,
                        checkpoint,
                        include_permissions,
                    )
            except Exception as e:
                logger.exception(
                    "Failed mid-iteration for drive '%s' in site '%s'",
                    current_drive_name,
                    site_descriptor.url,
                )
                yield _create_entity_failure(
                    f"{site_descriptor.url}|{current_drive_name}|bfs_iter",
                    f"Failed to iterate drive items after {item_count}: {e}",
                    (start_dt, end_dt),
                    e,
                )
                # Clear drive state to avoid resuming on the same broken drive.
                self._clear_drive_checkpoint_state(checkpoint)
                return checkpoint

            logger.info(
                "Processed %s items in drive '%s'", item_count, current_drive_name
            )

            if has_more_delta_pages:
                return checkpoint

            self._clear_drive_checkpoint_state(checkpoint)

        # Phase 4: Progression logic - determine next step
        # If we have more drives in current site, continue with current site
        if checkpoint.cached_drive_names and len(checkpoint.cached_drive_names) > 0:
            logger.debug(
                "Continuing with %s remaining drives in current site",
                len(checkpoint.cached_drive_names),
            )
            return checkpoint

        if (
            self.include_site_pages
            and not checkpoint.process_site_pages
            and checkpoint.current_site_descriptor is not None
        ):
            logger.info(
                "Processing site pages for site: %s",
                checkpoint.current_site_descriptor.url,
            )
            checkpoint.process_site_pages = True
            return checkpoint

        # Phase 5: Process site pages
        if (
            checkpoint.process_site_pages
            and checkpoint.current_site_descriptor is not None
        ):
            # Fetch SharePoint site pages (.aspx files)
            site_descriptor = checkpoint.current_site_descriptor
            start_dt = datetime.fromtimestamp(start, tz=timezone.utc)
            end_dt = datetime.fromtimestamp(end, tz=timezone.utc)
            try:
                site_pages = self._fetch_site_pages(
                    site_descriptor, start=start_dt, end=end_dt
                )
                for site_page in site_pages:
                    page_id = site_page.get("id")
                    page_label = site_page.get(
                        "webUrl", site_page.get("name", "Unknown")
                    )
                    # Skip a single broken page instead of aborting the
                    # rest of the site (perm-sync error, malformed field,
                    # token refresh blip, etc.).
                    try:
                        logger.debug("Processing site page: %s", page_label)
                        client_ctx: ClientContext | None = None
                        if include_permissions:
                            client_ctx = self._create_rest_client_context(
                                site_descriptor.url
                            )
                        yield (
                            _convert_sitepage_to_document(
                                site_page,
                                site_descriptor.drive_name,
                                client_ctx,
                                self.graph_client,
                                permission_cache=checkpoint.permission_cache,
                                include_permissions=include_permissions,
                                # Site pages have the site as their parent
                                parent_hierarchy_raw_node_id=site_descriptor.url,
                                treat_sharing_link_as_public=self.treat_sharing_link_as_public,
                            )
                        )
                    except Exception as e:
                        logger.warning(
                            "Failed to process site page '%s' in site %s: %s",
                            page_label,
                            site_descriptor.url,
                            e,
                            exc_info=True,
                        )
                        if page_id:
                            page_link = (
                                page_label if isinstance(page_label, str) else None
                            )
                            yield ConnectorFailure(
                                failed_document=DocumentFailure(
                                    document_id=page_id,
                                    document_link=page_link,
                                ),
                                failure_message=(
                                    f"SharePoint site page '{page_label}': {e}"
                                ),
                                exception=e,
                            )
                        else:
                            yield _create_entity_failure(
                                f"{site_descriptor.url}|site_page|{page_label}",
                                f"Failed to process site page '{page_label}': {e}",
                                (start_dt, end_dt),
                                e,
                            )
                logger.info(
                    "Finished processing site pages for site: %s",
                    site_descriptor.url,
                )
            except Exception as e:
                # Broadened from per-site Graph 4xx to any Exception:
                # _fetch_site_pages failures skip the site-pages stage
                # instead of failing the attempt. Per-page errors are
                # caught above.
                if (
                    isinstance(e, (ClientRequestException, HTTPError))
                    and e.response is not None
                ):
                    logger.warning(
                        "Skipping site pages for %s: Graph returned %s (%s)",
                        site_descriptor.url,
                        e.response.status_code,
                        graph_error_code(e.response),
                        exc_info=True,
                    )
                else:
                    logger.warning(
                        "Skipping site pages for %s: %s",
                        site_descriptor.url,
                        e,
                        exc_info=True,
                    )
                yield _create_entity_failure(
                    site_descriptor.url,
                    f"Failed to fetch site pages: {e}",
                    (start_dt, end_dt),
                    e,
                )

        # If no more drives, move to next site if available
        if (
            checkpoint.cached_site_descriptors
            and len(checkpoint.cached_site_descriptors) > 0
        ):
            current_site = (
                checkpoint.current_site_descriptor.url
                if checkpoint.current_site_descriptor
                else "unknown"
            )
            checkpoint.current_site_descriptor = (
                checkpoint.cached_site_descriptors.popleft()
            )
            checkpoint.cached_drive_names = None  # Reset for new site
            checkpoint.process_site_pages = False
            logger.info(
                "Finished site '%s', moving to next site: %s",
                current_site,
                checkpoint.current_site_descriptor.url,
            )
            logger.info(
                "Remaining sites to process: %s",
                len(checkpoint.cached_site_descriptors) + 1,
            )
            # Yield site hierarchy node for the new site
            yield from self._yield_site_hierarchy_node(
                checkpoint.current_site_descriptor,
                checkpoint,
                include_permissions=include_permissions,
            )
            return checkpoint

        # No more sites or drives - we're done
        current_site = (
            checkpoint.current_site_descriptor.url
            if checkpoint.current_site_descriptor
            else "unknown"
        )
        logger.info(
            "SharePoint processing complete. Finished last site: %s", current_site
        )
        checkpoint.has_more = False
        return checkpoint

    def load_from_checkpoint(
        self,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
        checkpoint: SharepointConnectorCheckpoint,
    ) -> CheckpointOutput[SharepointConnectorCheckpoint]:
        return self._load_from_checkpoint(
            start, end, checkpoint, include_permissions=False
        )

    def load_from_checkpoint_with_perm_sync(
        self,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
        checkpoint: SharepointConnectorCheckpoint,
    ) -> CheckpointOutput[SharepointConnectorCheckpoint]:
        return self._load_from_checkpoint(
            start, end, checkpoint, include_permissions=True
        )

    def _list_site_drives(
        self,
        site_url: str,
        site_drives_cache: dict[str, list[SiteDrive]],
    ) -> list[SiteDrive]:
        """List the drives (document libraries) of a site, memoized."""
        if site_url not in site_drives_cache:
            site = self.graph_client.sites.get_by_url(site_url)
            drives = site.drives.get().execute_query()
            site_drives_cache[site_url] = [
                SiteDrive(
                    drive_id=cast(str, d.id), name=d.name or "", web_url=d.web_url
                )
                for d in drives
            ]
        return site_drives_cache[site_url]

    def _resolve_driveitem_by_link(
        self,
        document_id: str,
        document_link: str,
        site_drives_cache: dict[str, list[SiteDrive]],
    ) -> ResolvedDriveItem:
        """Resolve a failed drive item's web URL to what's needed to re-fetch it.

        The recorded link only reliably yields the *site*: Graph returns the
        ``_layouts/15/Doc.aspx`` form as ``webUrl`` for Office documents, so the
        library/folder is not recoverable from the URL. We parse the site via
        ``_extract_site_and_drive_info``, list its drives, and probe each by item
        id until one resolves — all under the existing ``Sites.Read.All`` grant.
        ``site_drives_cache`` memoizes the per-site drive listing since targets
        cluster heavily by site. Raises ``ValueError`` if no drive resolves it.
        """
        descriptors = self._extract_site_and_drive_info([document_link])
        if not descriptors:
            raise ValueError(f"Could not parse a site from link '{document_link}'")
        site_url = descriptors[0].url

        for drive in self._list_site_drives(site_url, site_drives_cache):
            item_url = (
                f"{self.graph_api_base}/drives/{drive.drive_id}/items/{document_id}"
            )
            try:
                item_json = self.graph_api.get_json(item_url)
            except HTTPError as e:
                if e.response is not None and e.response.status_code == 404:
                    continue
                raise
            return ResolvedDriveItem(
                driveitem=DriveItemData.from_graph_json(item_json),
                drive_name=SHARED_DOCUMENTS_MAP.get(drive.name, drive.name),
                drive_web_url=drive.web_url,
                site_url=site_url,
            )

        raise ValueError(
            f"Item '{document_id}' not found in any library of site '{site_url}'"
        )

    def _reindex_drive_item(
        self,
        document_id: str,
        document_link: str,
        dedup: SharepointConnectorCheckpoint,
        site_drives_cache: dict[str, list[SiteDrive]],
        include_permissions: bool,
    ) -> Generator[Document | ConnectorFailure | HierarchyNode, None, None]:
        resolved = self._resolve_driveitem_by_link(
            document_id, document_link, site_drives_cache
        )
        # Emit the ancestor chain (site -> drive). The crawl yields these outside
        # the per-item loop, so the shared helper only emits folder nodes.
        yield from self._yield_site_hierarchy_node(
            SiteDescriptor(url=resolved.site_url, drive_name=None, folder_path=None),
            dedup,
            include_permissions=include_permissions,
        )
        if resolved.drive_web_url:
            yield from self._yield_drive_hierarchy_node(
                resolved.site_url,
                resolved.drive_web_url,
                resolved.drive_name,
                dedup,
                include_permissions=include_permissions,
            )
        yield from self._process_drive_item(
            resolved.driveitem,
            resolved.drive_name,
            resolved.drive_web_url,
            resolved.site_url,
            dedup,
            include_permissions,
            is_targeted_reindex=True,
        )

    def _reindex_site_page(
        self,
        document_id: str,
        document_link: str,
        dedup: SharepointConnectorCheckpoint,
        include_permissions: bool,
    ) -> Generator[Document | ConnectorFailure | HierarchyNode, None, None]:
        descriptors = self._extract_site_and_drive_info([document_link])
        if not descriptors:
            raise ValueError(
                f"Could not parse a site from site-page link '{document_link}'"
            )
        site_descriptor = SiteDescriptor(
            url=descriptors[0].url, drive_name=None, folder_path=None
        )
        site = self.graph_client.sites.get_by_url(site_descriptor.url)
        site.execute_query()

        page = self._fetch_single_site_page(cast(str, site.id), document_id)

        yield from self._yield_site_hierarchy_node(
            site_descriptor,
            dedup,
            include_permissions=include_permissions,
        )

        ctx: ClientContext | None = None
        if include_permissions:
            ctx = self._create_rest_client_context(site_descriptor.url)
        yield _convert_sitepage_to_document(
            page,
            site_descriptor.drive_name,
            ctx,
            self.graph_client,
            permission_cache=dedup.permission_cache,
            include_permissions=include_permissions,
            parent_hierarchy_raw_node_id=site_descriptor.url,
            treat_sharing_link_as_public=self.treat_sharing_link_as_public,
        )

    @override
    def reindex(
        self,
        errors: list[ConnectorFailure],
        include_permissions: bool = False,
    ) -> Generator[Document | ConnectorFailure | HierarchyNode, None, None]:
        """Re-fetch and re-index individual failed documents (Resolver).

        SharePoint doc ids are bare Graph driveItem/page ids that can't be fetched
        without their drive/site, so resolution is driven off each failure's
        recorded web URL (``document_link``). Targets with no usable link (e.g.
        admin-typed targets) yield an informative ConnectorFailure.
        """
        if self._graph_client is None:
            raise ConnectorMissingCredentialError("Sharepoint")

        # Throwaway checkpoint used purely as a dedup container for the shared
        # helpers (seen_document_ids / seen_hierarchy_node_raw_ids).
        dedup = self.build_dummy_checkpoint()
        site_drives_cache: dict[str, list[SiteDrive]] = {}
        # TODO(evan): Resolver.reindex is one-call-per-job and resolves targets
        # sequentially. If the interface grows batch semantics, Graph $batch
        # (20 sub-requests) could cut round trips on the per-item fetches.

        for error in errors:
            failed = error.failed_document
            if failed is None:
                continue
            document_id = failed.document_id
            document_link = failed.document_link
            if not document_link:
                yield ConnectorFailure(
                    failed_document=DocumentFailure(
                        document_id=document_id,
                        document_link=None,
                    ),
                    failure_message=(
                        "SharePoint targeted reindex needs the document's web URL "
                        "to locate it; none was recorded for this target."
                    ),
                )
                continue

            try:
                if "/sitepages/" in document_link.lower():
                    yield from self._reindex_site_page(
                        document_id, document_link, dedup, include_permissions
                    )
                else:
                    yield from self._reindex_drive_item(
                        document_id,
                        document_link,
                        dedup,
                        site_drives_cache,
                        include_permissions,
                    )
            except Exception as e:
                logger.warning(
                    "Failed to resolve SharePoint target %s (%s): %s",
                    document_id,
                    document_link,
                    e,
                )
                yield ConnectorFailure(
                    failed_document=DocumentFailure(
                        document_id=document_id,
                        document_link=document_link,
                    ),
                    failure_message=f"Failed to resolve during targeted reindex: {e}",
                    exception=e,
                )

    def build_dummy_checkpoint(self) -> SharepointConnectorCheckpoint:
        return SharepointConnectorCheckpoint(has_more=True)

    def validate_checkpoint_json(
        self, checkpoint_json: str
    ) -> SharepointConnectorCheckpoint:
        return SharepointConnectorCheckpoint.model_validate_json(checkpoint_json)

    @override
    def retrieve_all_slim_docs(
        self,
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,
        callback: IndexingHeartbeatInterface | None = None,  # noqa: ARG002
    ) -> GenerateSlimDocumentOutput:
        start_dt = (
            datetime.fromtimestamp(start, tz=timezone.utc)
            if start is not None
            else None
        )
        end_dt = (
            datetime.fromtimestamp(end, tz=timezone.utc) if end is not None else None
        )
        yield from self._fetch_slim_documents_from_sharepoint(
            start=start_dt,
            end=end_dt,
            include_permissions=False,
        )

    @override
    def retrieve_all_slim_docs_perm_sync(
        self,
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,
        callback: IndexingHeartbeatInterface | None = None,  # noqa: ARG002
    ) -> GenerateSlimDocumentOutput:
        start_dt = (
            datetime.fromtimestamp(start, tz=timezone.utc)
            if start is not None
            else None
        )
        end_dt = (
            datetime.fromtimestamp(end, tz=timezone.utc) if end is not None else None
        )
        yield from self._fetch_slim_documents_from_sharepoint(
            start=start_dt,
            end=end_dt,
            include_permissions=True,
        )


if __name__ == "__main__":
    from onyx.connectors.connector_runner import ConnectorRunner

    connector = SharepointConnector(sites=os.environ["SHAREPOINT_SITES"].split(","))

    connector.load_credentials(
        {
            "sp_client_id": os.environ["SHAREPOINT_CLIENT_ID"],
            "sp_client_secret": os.environ["SHAREPOINT_CLIENT_SECRET"],
            "sp_directory_id": os.environ["SHAREPOINT_CLIENT_DIRECTORY_ID"],
        }
    )

    # Create a time range from epoch to now
    end_time = datetime.now(timezone.utc)
    start_time = datetime.fromtimestamp(0, tz=timezone.utc)
    time_range = (start_time, end_time)

    # Initialize the runner with a batch size of 10
    runner: ConnectorRunner[SharepointConnectorCheckpoint] = ConnectorRunner(
        connector, batch_size=10, include_permissions=False, time_range=time_range
    )

    # Get initial checkpoint
    checkpoint = connector.build_dummy_checkpoint()

    # Run the connector
    while checkpoint.has_more:
        for doc_batch, _hierarchy_node_batch, failure, next_checkpoint in runner.run(
            checkpoint
        ):
            if doc_batch:
                print(f"Retrieved batch of {len(doc_batch)} documents")
                for test_doc in doc_batch:
                    print(f"Document: {test_doc.semantic_identifier}")
            if failure:
                print(f"Failure: {failure.failure_message}")
            if next_checkpoint:
                checkpoint = next_checkpoint
