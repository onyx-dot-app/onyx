import copy
import fnmatch
import html
import os
import re
from collections import deque
from collections.abc import Generator, Iterable
from datetime import datetime, timezone
from typing import Any, cast
from urllib.parse import SplitResult, quote, unquote, urlsplit

from pydantic import AliasChoices, BaseModel, Field
from typing_extensions import override

from onyx.configs.app_configs import (
    INDEX_BATCH_SIZE,
    SHAREPOINT_EXHAUSTIVE_AD_ENUMERATION,
)
from onyx.configs.constants import DocumentSource
from onyx.connectors.credentials_provider import OnyxStaticCredentialsProvider
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.interfaces import (
    CheckpointedConnectorWithPermSync,
    CheckpointOutput,
    CredentialsConnector,
    CredentialsProviderInterface,
    GenerateSlimDocumentOutput,
    IndexingHeartbeatInterface,
    Resolver,
    SecondsSinceUnixEpoch,
    SlimConnector,
    SlimConnectorWithPermSync,
)
from onyx.connectors.microsoft_utils.config import (
    DEFAULT_AUTHORITY_HOST,
    DEFAULT_GRAPH_API_HOST,
    DEFAULT_SHAREPOINT_DOMAIN_SUFFIX,
)
from onyx.connectors.microsoft_utils.drive_delta import build_delta_start_url
from onyx.connectors.microsoft_utils.drive_items import (
    DriveFolderReference,
    DriveItemContentError,
    DriveItemData,
    build_item_relative_path,
    extract_folder_path_from_parent_reference,
    is_path_excluded,
    iter_delta_page_files,
    parse_graph_datetime,
    timestamp_in_window,
)
from onyx.connectors.microsoft_utils.graph_auth import MicrosoftAuthMethod
from onyx.connectors.microsoft_utils.graph_env import resolve_microsoft_environment
from onyx.connectors.microsoft_utils.graph_errors import MicrosoftGraphError
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
    validate_content_types,
    validate_site_url,
)
from onyx.connectors.sharepoint.models import SharepointDrive
from onyx.connectors.sharepoint.source_operations import (
    CONFIG_AUTHORITY_HOST,
    CONFIG_GRAPH_API_HOST,
    CONFIG_SITES,
    GRAPH_API_VERSION,
    SharepointSourceOperations,
)
from onyx.db.enums import HierarchyNodeType
from onyx.file_processing.extract_file_text import get_file_ext
from onyx.file_processing.file_types import OnyxFileExtensions
from onyx.file_store.staging import RawFileCallback
from onyx.utils.logger import setup_logger

logger = setup_logger()
SLIM_BATCH_SIZE = 1000


SHARED_DOCUMENTS_MAP = {
    "Documents": "Shared Documents",
    "Dokumente": "Freigegebene Dokumente",
    "Documentos": "Documentos compartidos",
}

# `driveType` values that identify a user's primary OneDrive (as opposed to an
# extra "documentLibrary" added to the personal site). OneDrive personal returns
# "personal", OneDrive for Business returns "business".
ONEDRIVE_PRIMARY_DRIVE_TYPES = frozenset({"personal", "business"})
PERSONAL_SITE_URL_MARKER = "/personal/"
# A listed site on the OneDrive host is a personal site, which this connector
# leaves to the OneDrive connector.
ONEDRIVE_HOST_MARKER = "-my.sharepoint"

ASPX_EXTENSION = ".aspx"


def is_site_excluded(site_url: str, excluded_site_patterns: list[str]) -> bool:
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
    drive_id: str
    display_name: str
    web_url: str
    list_id: str | None = None


class FetchedDriveItem(BaseModel):
    driveitem: DriveItemData
    drive: SiteDrive
    configured_folder: DriveFolderReference | None = None


class ResolvedDriveItem(BaseModel):
    """The result of mapping a failed item's link back to a fetchable item."""

    driveitem: DriveItemData
    drive: SiteDrive
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


def build_folder_server_relative_path(drive_web_url: str, folder_path: str) -> str:
    """The decoded server-relative path SharePoint uses to find a folder.

    Uses the library's web URL, not its display name: SharePoint strips
    characters like "&" from the library URL, and renames keep the old URL.
    """
    library_path = unquote(urlsplit(drive_web_url).path).rstrip("/")
    return f"{library_path}/{unquote(folder_path)}"


def _drive_url_name(drive_web_url: str | None) -> str | None:
    if not drive_web_url:
        return None
    return unquote(urlsplit(drive_web_url).path.rstrip("/").rsplit("/", 1)[-1])


def _drives_matching_url_name(
    drives: Iterable[SharepointDrive], url_name: str
) -> list[SharepointDrive]:
    """Match drives by the library segment of their URL, case-insensitively.

    A site URL scoped to a library carries the URL segment, which can differ from
    the display name: SharePoint strips characters like "&", and renames keep the
    old URL.
    """
    return [
        drive
        for drive in drives
        if (_drive_url_name(drive.web_url) or "").lower() == url_name.lower()
    ]


class SharepointConnectorCheckpoint(ConnectorCheckpoint):
    cached_site_descriptors: deque[SiteDescriptor] | None = None
    current_site_descriptor: SiteDescriptor | None = None

    cached_drives: deque[SiteDrive] | None = None
    current_drive: SiteDrive | None = None
    current_folder: DriveFolderReference | None = None
    legacy_cached_drive_names: deque[str] | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "legacy_cached_drive_names", "cached_drive_names"
        ),
        exclude=True,
    )
    legacy_current_drive_name: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "legacy_current_drive_name", "current_drive_name"
        ),
        exclude=True,
    )
    legacy_current_drive_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices("legacy_current_drive_id", "current_drive_id"),
        exclude=True,
    )
    legacy_current_drive_web_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "legacy_current_drive_web_url", "current_drive_web_url"
        ),
        exclude=True,
    )
    # Next delta API page URL for per-page checkpointing within a drive.
    # When set, Phase 3b fetches one page at a time so progress is persisted
    # between pages.  None means BFS path or no active delta traversal.
    current_drive_delta_next_link: str | None = None
    current_drive_delta_resync_attempted: bool = False

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


def is_graph_invalid_request(error: MicrosoftGraphError) -> bool:
    """True for the generic Graph ``invalidRequest`` 400, which has no
    actionable inner code. The site-pages endpoint answers it when a page has
    a corrupt canvas layout (duplicate web-part ids, SharePoint/sp-dev-docs#8822)."""
    return error.status == 400 and error.code == GRAPH_INVALID_REQUEST_CODE


def _validate_credential_fields(credentials: dict[str, Any]) -> None:
    auth_method = MicrosoftAuthMethod.parse(credentials.get("authentication_method"))
    if not credentials.get("sp_client_id"):
        raise ConnectorValidationError("Client ID is required")
    if not credentials.get("sp_directory_id"):
        raise ConnectorValidationError("Directory (tenant) ID is required")
    if auth_method is MicrosoftAuthMethod.CERTIFICATE and not (
        credentials.get("sp_private_key") and credentials.get("sp_certificate_password")
    ):
        raise ConnectorValidationError(
            "Private key and certificate password are required for certificate authentication"
        )


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
    drive: SiteDrive,
    ops: SharepointSourceOperations,
    site_url: str,
    include_permissions: bool = False,
    parent_hierarchy_raw_node_id: str | None = None,
    treat_sharing_link_as_public: bool = False,
    raw_file_callback: RawFileCallback | None = None,
    permission_cache: SharepointPermissionCache | None = None,
) -> Document | ConnectorFailure | None:
    if not driveitem.name or not driveitem.id:
        raise ValueError("DriveItem name/id is required")

    permission_cache = permission_cache or SharepointPermissionCache()

    try:
        content = ops.download_item(item=driveitem, raw_file_callback=raw_file_callback)
    except DriveItemContentError as e:
        cause = e.__cause__ if isinstance(e.__cause__, Exception) else None
        return _create_document_failure(driveitem, str(e), cause)

    if content is None:
        return None

    sections = content.sections
    staged_file_id = content.staged_file_id

    if include_permissions:
        logger.info("Getting external access for %s", driveitem.name)
        external_access = get_sharepoint_external_access(
            reader=ops,
            site_url=site_url,
            permission_cache=permission_cache,
            drive_item=driveitem,
            list_id=drive.list_id,
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
        metadata={"drive": drive.display_name},
        parent_hierarchy_raw_node_id=parent_hierarchy_raw_node_id,
        file_id=staged_file_id,
    )
    return doc


def _convert_sitepage_to_document(
    site_page: dict[str, Any],
    site_name: str | None,
    ops: SharepointSourceOperations,
    site_url: str,
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
    semantic_identifier = semantic_identifier.removesuffix(ASPX_EXTENSION)

    if include_permissions:
        external_access = get_sharepoint_external_access(
            reader=ops,
            site_url=site_url,
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
    drive: SiteDrive,
    ops: SharepointSourceOperations,
    site_url: str,
    permission_cache: SharepointPermissionCache,
    parent_hierarchy_raw_node_id: str | None = None,
    treat_sharing_link_as_public: bool = False,
) -> SlimDocument:
    external_access = get_sharepoint_external_access(
        reader=ops,
        site_url=site_url,
        permission_cache=permission_cache,
        drive_item=driveitem,
        list_id=drive.list_id,
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
    ops: SharepointSourceOperations,
    site_url: str,
    permission_cache: SharepointPermissionCache,
    parent_hierarchy_raw_node_id: str | None = None,
    treat_sharing_link_as_public: bool = False,
) -> SlimDocument:
    """Convert a SharePoint site page to a SlimDocument object."""
    page_id: str | None = site_page.get("id")
    if page_id is None:
        raise ValueError("Site page ID is required")

    external_access: ExternalAccess = get_sharepoint_external_access(
        reader=ops,
        site_url=site_url,
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


def _strip_share_link_tokens(path: str) -> list[str]:
    # Share links often include a token prefix like /:f:/r/ or /:x:/r/.
    segments: list[str] = [segment for segment in path.split("/") if segment]
    if segments and segments[0].startswith(":"):
        segments = segments[1:]
        if segments and segments[0] in {"r", "s", "g"}:
            segments = segments[1:]
    return segments


def _normalize_sharepoint_url(url: str) -> tuple[str | None, list[str]]:
    try:
        parsed: SplitResult = urlsplit(url)
    except ValueError:
        logger.warning("Sharepoint URL '%s' could not be parsed", url)
        return None, []

    if not parsed.scheme or not parsed.netloc:
        logger.warning(
            "Sharepoint URL '%s' is not a valid absolute URL (missing scheme or host)",
            url,
        )
        return None, []

    path_segments: list[str] = _strip_share_link_tokens(parsed.path)
    return f"{parsed.scheme}://{parsed.netloc}", path_segments


def extract_site_descriptors(site_urls: list[str]) -> list[SiteDescriptor]:
    """The site, library and folder each URL names. A URL that names no site
    is logged and dropped."""
    site_data_list: list[SiteDescriptor] = []
    for url in site_urls:
        base_url, parts = _normalize_sharepoint_url(url.strip())
        if base_url is None:
            continue

        lower_parts: list[str] = [part.lower() for part in parts]
        site_type_index: int | None = None
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

        site_path: list[str] = parts[: site_type_index + 2]
        remaining_parts: list[str] = parts[site_type_index + 2 :]
        site_url: str = f"{base_url}/" + "/".join(site_path)

        # Extract drive name and folder path
        drive_name: str | None
        folder_path: str | None
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


def select_site_drive(
    site_descriptor: SiteDescriptor,
    configured_url_name: str,
    drives: Iterable[SharepointDrive],
) -> SiteDrive | None:
    """The library a site URL names by its URL segment, or the primary
    OneDrive of a personal site. None when no library matches."""
    listed: list[SharepointDrive] = list(drives)
    matched: list[SharepointDrive] = _drives_matching_url_name(
        listed, configured_url_name
    )
    if len(matched) > 1:
        raise ValueError(
            f"Drive URL segment '{configured_url_name}' is ambiguous in "
            f"site '{site_descriptor.url}'"
        )

    is_personal_site: bool = PERSONAL_SITE_URL_MARKER in site_descriptor.url.lower()
    if not matched and is_personal_site and listed:
        matched = [
            d
            for d in listed
            if (d.drive_type or "").lower() in ONEDRIVE_PRIMARY_DRIVE_TYPES
        ]
        if len(matched) > 1:
            raise ValueError(
                f"Could not unambiguously resolve the primary OneDrive for "
                f"personal site '{site_descriptor.url}'"
            )

    if not matched:
        logger.warning("Drive '%s' not found", configured_url_name)
        return None

    drive: SharepointDrive = matched[0]
    logger.info("Found drive: %s (web_url: %s)", drive.name, drive.web_url)
    return site_drive_from_graph(drive)


def site_drive_from_graph(drive: SharepointDrive) -> SiteDrive:
    if not drive.id or not drive.name or not drive.web_url:
        raise ValueError("Graph drive is missing required traversal metadata")
    return SiteDrive(
        drive_id=drive.id,
        list_id=drive.list_id,
        display_name=SHARED_DOCUMENTS_MAP.get(drive.name, drive.name),
        web_url=drive.web_url,
    )


class SharepointConnector(
    SlimConnector,
    SlimConnectorWithPermSync,
    CheckpointedConnectorWithPermSync[SharepointConnectorCheckpoint],
    CredentialsConnector,
    Resolver,
):
    slim_listing_honors_indexing_start = True

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
        exhaustive_ad_enumeration: bool = SHAREPOINT_EXHAUSTIVE_AD_ENUMERATION,
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
        # Read by EE group sync: also enumerate every Entra group in the tenant.
        self.exhaustive_ad_enumeration = exhaustive_ad_enumeration
        self.site_descriptors: list[SiteDescriptor] = extract_site_descriptors(sites)
        self._ops: SharepointSourceOperations | None = None
        self.include_site_pages = include_site_pages
        self.include_site_documents = include_site_documents

        resolved_env = resolve_microsoft_environment(graph_api_host, authority_host)
        self.authority_host = resolved_env.authority_host
        self.graph_api_host = resolved_env.graph_host
        self.graph_api_base = f"{self.graph_api_host}/{GRAPH_API_VERSION}"
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
        validate_content_types(self.include_site_documents, self.include_site_pages)
        for site_url in self.sites:
            self._validate_site_url(site_url)

    def _validate_site_url(self, site_url: str) -> None:
        """The tenant host is known once credentials are loaded. Before that
        only the cloud suffix is checked."""
        tenant_domain = (
            self._ops.resolve_tenant_domain() if self._ops is not None else None
        )
        validate_site_url(site_url, self.sharepoint_domain_suffix, tenant_domain)

    def probe_group_members_permission(self) -> None:
        """Verify the Azure AD app can enumerate Azure AD group members via Graph.

        Required for permission sync, which expands Azure AD groups attached to
        SharePoint role assignments via `GET /v1.0/groups/{id}/members`. Tested
        via `GET /v1.0/groups?$top=1`, which requires the same permission set
        (GroupMember.Read.All / Group.Read.All / Directory.Read.All) so a 403
        here reliably predicts a 403 on the members call. Only runs when
        credentials have been loaded.
        """
        if self._ops is None:
            return
        try:
            self.ops.list_entra_groups(page_size=1)
        except MicrosoftGraphError as error:
            if error.status in (401, 403):
                raise ConnectorValidationError(
                    "The Azure AD app registration is missing the required Microsoft Graph "
                    "permission to enumerate Azure AD group members. Please grant "
                    "'GroupMember.Read.All' (application permission) in the Azure portal "
                    "and re-run admin consent."
                ) from error
            logger.warning(
                "Group members permission probe failed (non-blocking): %s", error
            )
        except ConnectorValidationError:
            raise
        except Exception as e:
            logger.warning(
                "Group members permission probe failed (non-blocking): %s", e
            )

    @property
    def ops(self) -> SharepointSourceOperations:
        if self._ops is None:
            raise ConnectorMissingCredentialError("Sharepoint")
        return self._ops

    def _resolve_drive(
        self,
        site_descriptor: SiteDescriptor,
        configured_url_name: str,
    ) -> SiteDrive | None:
        drives = self._list_drives_for_site(site_descriptor.url)
        logger.info("Found drives: %s", [d.name for d in drives])
        return select_site_drive(site_descriptor, configured_url_name, drives)

    def _fetch_driveitems(
        self,
        site_descriptor: SiteDescriptor,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> Generator[FetchedDriveItem, None, None]:
        """Yield items and hierarchy context lazily for all drives in a site."""
        try:
            drives = self._list_drives_for_site(site_descriptor.url)
        # The site read and its drive listing run together here, before any
        # item is yielded, so a refusal of either is the whole site, never a
        # partial one.
        except MicrosoftGraphError as e:
            if not e.is_permanent_refusal:
                raise
            logger.warning(
                "Skipping site %s, Graph refused it for good: %s",
                site_descriptor.url,
                e,
            )
            return
        logger.debug("Found drives: %s", [d.name for d in drives])

        if site_descriptor.drive_name:
            resolved = select_site_drive(
                site_descriptor, site_descriptor.drive_name, drives
            )
            if resolved is None:
                return
            site_drives = [resolved]
        else:
            site_drives = [site_drive_from_graph(drive) for drive in drives]

        for drive in site_drives:
            configured_folder = None
            if site_descriptor.folder_path:
                configured_folder = self.ops.resolve_folder(
                    drive_id=drive.drive_id, folder_path=site_descriptor.folder_path
                )
                item_iter = self.ops.iter_folder_items(
                    drive_id=drive.drive_id,
                    folder_id=configured_folder.id,
                    start=start,
                    end=end,
                )
            else:
                item_iter = self.ops.iter_delta_items(
                    drive_id=drive.drive_id, start=start, end=end
                )

            for item in item_iter:
                yield FetchedDriveItem(
                    driveitem=item,
                    drive=drive,
                    configured_folder=configured_folder,
                )

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
            if is_site_excluded(sd.url, self.excluded_sites):
                logger.info("Excluding site by denylist: %s", sd.url)
                continue
            result.append(sd)
        return result

    def fetch_sites(self) -> list[SiteDescriptor]:
        site_urls = self.ops.list_site_urls()

        if not site_urls:
            raise RuntimeError("No sites found in the tenant")

        # OneDrive personal sites should not be indexed with SharepointConnector
        site_descriptors = [
            SiteDescriptor(url=site_url, drive_name=None, folder_path=None)
            for site_url in site_urls
            if ONEDRIVE_HOST_MARKER not in site_url
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
        site_id = self.ops.get_site_id(site_url=site_descriptor.url)

        next_link: str | None = None
        total_yielded = 0
        yielded_ids: set[str] = set()

        while True:
            try:
                listing = self.ops.list_site_pages(
                    site_id=site_id, next_link=next_link, expand_canvas=True
                )
            except MicrosoftGraphError as e:
                if e.status == 404:
                    logger.warning("Site page not found: %s", next_link or site_id)
                    break
                if is_graph_invalid_request(e):
                    logger.warning(
                        "$expand=canvasLayout on the LIST endpoint returned 400 for site %s. Falling back to per-page expansion.",
                        site_descriptor.url,
                    )
                    yield from self._fetch_site_pages_individually(
                        site_id, start, end, skip_ids=yielded_ids
                    )
                    return
                raise

            for page in listing.pages:
                if not _site_page_in_time_window(page, start, end):
                    continue
                total_yielded += 1
                page_id = page.get("id")
                if page_id:
                    yielded_ids.add(page_id)
                yield page

            next_link = listing.next_link
            if next_link is None:
                break

        logger.debug("Yielded %s site pages for %s", total_yielded, site_descriptor.url)

    def _fetch_site_pages_individually(
        self,
        site_id: str,
        start: datetime | None = None,
        end: datetime | None = None,
        skip_ids: set[str] | None = None,
    ) -> Generator[dict[str, Any], None, None]:
        """Fallback for _fetch_site_pages: list pages without $expand, then
        expand canvasLayout on each page individually.

        The Graph API's LIST endpoint can return 400 when $expand=canvasLayout
        is used and *any* page in the site has a corrupt canvas layout (e.g.
        duplicate web part IDs, SharePoint/sp-dev-docs#8822). Since the LIST
        expansion is all-or-nothing, a single bad page poisons the entire
        response. This method works around it by fetching metadata first, then
        expanding each page individually so only the broken page loses its
        canvas content.

        ``skip_ids`` contains page IDs already yielded by the caller before the
        fallback was triggered, preventing duplicates.
        """
        next_link: str | None = None
        total_yielded = 0
        _skip_ids = skip_ids or set()

        while True:
            try:
                listing = self.ops.list_site_pages(
                    site_id=site_id, next_link=next_link, expand_canvas=False
                )
            except MicrosoftGraphError as e:
                if e.status == 404:
                    break
                raise

            for page in listing.pages:
                if not _site_page_in_time_window(page, start, end):
                    continue

                page_id = page.get("id")
                if page_id and page_id in _skip_ids:
                    continue

                if not page_id:
                    total_yielded += 1
                    yield page
                    continue

                expanded = self._try_expand_single_page(site_id, page_id, page)
                total_yielded += 1
                yield expanded

            next_link = listing.next_link
            if next_link is None:
                break

        logger.debug(
            "Yielded %s site pages (per-page expansion fallback)", total_yielded
        )

    def _try_expand_single_page(
        self,
        site_id: str,
        page_id: str,
        fallback_page: dict[str, Any],
    ) -> dict[str, Any]:
        """Try to GET a single page with $expand=canvasLayout. On 400, return
        the metadata-only fallback so the page is still indexed (without canvas
        content)."""
        try:
            return self.ops.get_site_page(
                site_id=site_id, page_id=page_id, expand_canvas=True
            )
        except MicrosoftGraphError as e:
            if is_graph_invalid_request(e):
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
        metadata = self.ops.get_site_page(
            site_id=site_id, page_id=page_id, expand_canvas=False
        )
        return self._try_expand_single_page(site_id, page_id, metadata)

    @staticmethod
    def _clear_drive_checkpoint_state(
        checkpoint: "SharepointConnectorCheckpoint",
    ) -> None:
        checkpoint.current_drive = None
        checkpoint.current_folder = None
        checkpoint.current_drive_delta_next_link = None
        checkpoint.current_drive_delta_resync_attempted = False
        checkpoint.seen_document_ids.clear()

    @staticmethod
    def _match_legacy_drive(
        drives: list[SiteDrive],
        *,
        drive_id: str | None = None,
        web_url: str | None = None,
        name: str | None = None,
    ) -> SiteDrive | None:
        if drive_id:
            matches = [drive for drive in drives if drive.drive_id == drive_id]
        elif web_url:
            matches = [
                drive
                for drive in drives
                if drive.web_url.rstrip("/").casefold()
                == web_url.rstrip("/").casefold()
            ]
        elif name:
            expected_names = {name.casefold()}
            expected_names.update(
                graph_name.casefold()
                for graph_name, configured_name in SHARED_DOCUMENTS_MAP.items()
                if configured_name.casefold() == name.casefold()
            )
            matches = [
                drive
                for drive in drives
                if drive.display_name.casefold() in expected_names
                or (_drive_url_name(drive.web_url) or "").casefold() == name.casefold()
            ]
        else:
            return None
        if len(matches) > 1:
            raise ValueError("Legacy drive reference is ambiguous")
        return matches[0] if matches else None

    def _migrate_legacy_drive_checkpoint(
        self,
        checkpoint: SharepointConnectorCheckpoint,
    ) -> None:
        site = checkpoint.current_site_descriptor
        has_legacy_state = any(
            (
                checkpoint.legacy_cached_drive_names is not None,
                checkpoint.legacy_current_drive_id,
                checkpoint.legacy_current_drive_name,
                checkpoint.legacy_current_drive_web_url,
            )
        )
        if site is None or not has_legacy_state:
            return

        listed_drives = self._get_drives_for_site(site.url)
        if checkpoint.legacy_cached_drive_names is not None:
            checkpoint.cached_drives = deque(
                drive
                for name in checkpoint.legacy_cached_drive_names
                if (drive := self._match_legacy_drive(listed_drives, name=name))
                is not None
            )
            checkpoint.legacy_cached_drive_names = None

        had_current = bool(
            checkpoint.legacy_current_drive_id
            or checkpoint.legacy_current_drive_name
            or checkpoint.legacy_current_drive_web_url
        )
        if had_current:
            checkpoint.current_drive = self._match_legacy_drive(
                listed_drives,
                drive_id=checkpoint.legacy_current_drive_id,
                web_url=checkpoint.legacy_current_drive_web_url,
                name=checkpoint.legacy_current_drive_name,
            )
            if checkpoint.current_drive is None:
                logger.warning(
                    "Legacy checkpoint drive no longer exists in %s", site.url
                )
                self._clear_drive_checkpoint_state(checkpoint)

        checkpoint.legacy_current_drive_name = None
        checkpoint.legacy_current_drive_id = None
        checkpoint.legacy_current_drive_web_url = None

        if (
            checkpoint.current_drive
            and site.folder_path
            and not checkpoint.current_folder
        ):
            checkpoint.current_folder = self.ops.resolve_folder(
                drive_id=checkpoint.current_drive.drive_id,
                folder_path=site.folder_path,
            )

    def _fetch_slim_documents_from_sharepoint(
        self,
        start: datetime | None = None,
        end: datetime | None = None,
        include_permissions: bool = True,
    ) -> GenerateSlimDocumentOutput:
        site_descriptors = self._filter_excluded_sites(
            self.site_descriptors or self.fetch_sites()
        )

        temp_checkpoint = SharepointConnectorCheckpoint(has_more=True)

        doc_batch: list[SlimDocument | HierarchyNode] = []
        for site_descriptor in site_descriptors:
            site_url = site_descriptor.url
            temp_checkpoint.current_site_descriptor = site_descriptor

            doc_batch.extend(
                self._yield_site_hierarchy_node(
                    site_descriptor,
                    temp_checkpoint,
                    include_permissions=include_permissions,
                )
            )

            if self.include_site_documents:
                for fetched_item in self._fetch_driveitems(
                    site_descriptor=site_descriptor,
                    start=start,
                    end=end,
                ):
                    driveitem = fetched_item.driveitem
                    drive = fetched_item.drive
                    temp_checkpoint.current_folder = fetched_item.configured_folder
                    if include_permissions and not drive.list_id:
                        logger.warning(
                            "Skipping permission sync for drive %s without a list ID",
                            drive.drive_id,
                        )
                        continue
                    if self._is_driveitem_excluded(driveitem):
                        logger.debug(
                            "Excluding by path denylist: %s", driveitem.web_url
                        )
                        continue

                    doc_batch.extend(
                        self._yield_drive_hierarchy_node(
                            site_url,
                            drive,
                            temp_checkpoint,
                            include_permissions=include_permissions,
                        )
                    )

                    folder_path = extract_folder_path_from_parent_reference(
                        driveitem.parent_reference_path
                    )
                    if folder_path:
                        doc_batch.extend(
                            self._yield_folder_hierarchy_nodes(
                                site_url,
                                drive,
                                folder_path,
                                temp_checkpoint,
                                include_permissions=include_permissions,
                            )
                        )

                    parent_hierarchy_url = (
                        self._folder_url(drive, folder_path, temp_checkpoint)
                        if folder_path
                        else drive.web_url
                    )

                    try:
                        logger.debug("Processing: %s", driveitem.web_url)
                        if include_permissions:
                            doc_batch.append(
                                _convert_driveitem_to_slim_document(
                                    driveitem,
                                    drive,
                                    self.ops,
                                    site_descriptor.url,
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
                                doc_batch.append(
                                    _convert_sitepage_to_slim_document(
                                        site_page,
                                        self.ops,
                                        site_descriptor.url,
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
                    if isinstance(e, MicrosoftGraphError):
                        logger.warning(
                            "Skipping slim site pages for %s: Graph returned %s (%s)",
                            site_descriptor.url,
                            e.status,
                            e.code,
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
        self.set_credentials_provider(
            OnyxStaticCredentialsProvider(
                None, DocumentSource.SHAREPOINT.value, credentials
            )
        )
        return None

    def set_credentials_provider(
        self, credentials_provider: CredentialsProviderInterface
    ) -> None:
        # Checked here, on both credential paths, so a bad credential fails
        # pairing as a ConnectorValidationError instead of a MicrosoftAuthError
        # on the first Graph call.
        _validate_credential_fields(credentials_provider.get_credentials())
        self._ops = SharepointSourceOperations(
            credentials_provider=credentials_provider,
            connector_specific_config={
                CONFIG_AUTHORITY_HOST: self.authority_host,
                CONFIG_GRAPH_API_HOST: self.graph_api_host,
                CONFIG_SITES: self.sites,
            },
        )

    def _get_drives_for_site(
        self,
        site_url: str,
        cache: dict[str, list[SiteDrive]] | None = None,
    ) -> list[SiteDrive]:
        if cache is not None and site_url in cache:
            return cache[site_url]
        drives = self._list_drives_for_site(site_url)
        result = [site_drive_from_graph(drive) for drive in drives]
        if cache is not None:
            cache[site_url] = result
        return result

    def _list_drives_for_site(self, site_url: str) -> list[SharepointDrive]:
        return self.ops.list_drives(site_url=site_url)

    @staticmethod
    def _folder_url(
        drive: SiteDrive,
        folder_path: str,
        checkpoint: SharepointConnectorCheckpoint,
    ) -> str:
        site = checkpoint.current_site_descriptor
        if (
            checkpoint.current_folder
            and site
            and site.folder_path
            and unquote(site.folder_path).strip("/").casefold()
            == unquote(folder_path).strip("/").casefold()
        ):
            return checkpoint.current_folder.web_url
        encoded_path = quote(unquote(folder_path), safe="/")
        return f"{drive.web_url.rstrip('/')}/{encoded_path}"

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
            external_access = get_sharepoint_hierarchy_node_external_access(
                self.ops,
                site_url,
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
        drive: SiteDrive,
        checkpoint: SharepointConnectorCheckpoint,
        include_permissions: bool = False,
    ) -> Generator[HierarchyNode, None, None]:
        """Yield a hierarchy node for a drive if not already yielded.

        Uses drive.web_url as the raw_node_id (exact URL from API).
        """
        if drive.web_url in checkpoint.seen_hierarchy_node_raw_ids:
            return

        checkpoint.seen_hierarchy_node_raw_ids.add(drive.web_url)
        external_access = None
        if include_permissions:
            external_access = get_sharepoint_hierarchy_node_external_access(
                self.ops,
                site_url,
                checkpoint.permission_cache,
                HierarchyNodeType.DRIVE,
                list_id=drive.list_id,
            )

        yield HierarchyNode(
            raw_node_id=drive.web_url,
            raw_parent_id=site_url,  # Site URL is parent
            display_name=drive.display_name,
            link=drive.web_url,
            node_type=HierarchyNodeType.DRIVE,
            external_access=external_access,
        )

    def _yield_folder_hierarchy_nodes(
        self,
        site_url: str,
        drive: SiteDrive,
        folder_path: str,
        checkpoint: SharepointConnectorCheckpoint,
        include_permissions: bool = False,
    ) -> Generator[HierarchyNode, None, None]:
        if not folder_path:
            return

        path_parts = folder_path.split("/")
        for i, part in enumerate(path_parts):
            current_path = "/".join(path_parts[: i + 1])
            folder_url = self._folder_url(drive, current_path, checkpoint)

            if folder_url in checkpoint.seen_hierarchy_node_raw_ids:
                continue

            checkpoint.seen_hierarchy_node_raw_ids.add(folder_url)
            external_access = None
            if include_permissions:
                folder_server_relative_path = build_folder_server_relative_path(
                    drive.web_url, current_path
                )
                # One folder must not fail the whole sync. A node without
                # external_access keeps the permissions it already has.
                try:
                    external_access = get_sharepoint_hierarchy_node_external_access(
                        self.ops,
                        site_url,
                        checkpoint.permission_cache,
                        HierarchyNodeType.FOLDER,
                        folder_server_relative_path=folder_server_relative_path,
                    )
                except Exception as e:
                    logger.warning(
                        "Failed to get permissions for folder %s, skipping: %s",
                        folder_server_relative_path,
                        e,
                    )

            parent_url = (
                drive.web_url
                if i == 0
                else self._folder_url(drive, "/".join(path_parts[:i]), checkpoint)
            )

            yield HierarchyNode(
                raw_node_id=folder_url,
                raw_parent_id=parent_url,
                display_name=part,
                link=folder_url,
                node_type=HierarchyNodeType.FOLDER,
                external_access=external_access,
            )

    def _process_drive_item(
        self,
        driveitem: DriveItemData,
        drive: SiteDrive,
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
        if folder_path:
            yield from self._yield_folder_hierarchy_nodes(
                site_url,
                drive,
                folder_path,
                checkpoint,
                include_permissions=include_permissions,
            )

        parent_hierarchy_url = (
            self._folder_url(drive, folder_path, checkpoint)
            if folder_path
            else drive.web_url
        )

        try:
            doc_or_failure = _convert_driveitem_to_document_with_permissions(
                driveitem,
                drive,
                self.ops,
                site_url,
                permission_cache=checkpoint.permission_cache,
                include_permissions=include_permissions,
                parent_hierarchy_raw_node_id=parent_hierarchy_url,
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
        if self._ops is None:
            raise ConnectorMissingCredentialError("Sharepoint")

        checkpoint = copy.deepcopy(checkpoint)
        self._migrate_legacy_drive_checkpoint(checkpoint)

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
            if checkpoint.cached_site_descriptors:
                checkpoint.current_site_descriptor = (
                    checkpoint.cached_site_descriptors.popleft()
                )
                logger.info(
                    "Starting with site: %s", checkpoint.current_site_descriptor.url
                )
                yield from self._yield_site_hierarchy_node(
                    checkpoint.current_site_descriptor,
                    checkpoint,
                    include_permissions=include_permissions,
                )
                return checkpoint

        if checkpoint.current_site_descriptor and checkpoint.cached_drives is None:
            if not self.include_site_documents:
                logger.debug("Documents disabled, skipping drive initialization")
                checkpoint.cached_drives = deque()
                return checkpoint

            logger.info(
                "Initializing drives for site: %s",
                checkpoint.current_site_descriptor.url,
            )

            try:
                if checkpoint.current_site_descriptor.drive_name:
                    logger.info(
                        "Using explicitly specified drive: %s",
                        checkpoint.current_site_descriptor.drive_name,
                    )
                    drive = self._resolve_drive(
                        checkpoint.current_site_descriptor,
                        checkpoint.current_site_descriptor.drive_name,
                    )
                    checkpoint.cached_drives = deque([drive] if drive else [])
                else:
                    drives = self._get_drives_for_site(
                        checkpoint.current_site_descriptor.url
                    )
                    checkpoint.cached_drives = deque(drives)

                if not checkpoint.cached_drives:
                    logger.warning(
                        "No accessible drives found for site: %s",
                        checkpoint.current_site_descriptor.url,
                    )
                else:
                    logger.info(
                        "Found %s drives: %s",
                        len(checkpoint.cached_drives),
                        [drive.display_name for drive in checkpoint.cached_drives],
                    )

            except Exception as e:
                logger.error(
                    "Failed to initialize drives for site: %s: %s",
                    checkpoint.current_site_descriptor.url,
                    e,
                )
                start_dt = datetime.fromtimestamp(start, tz=timezone.utc)
                end_dt = datetime.fromtimestamp(end, tz=timezone.utc)
                yield _create_entity_failure(
                    checkpoint.current_site_descriptor.url,
                    f"Failed to access site: {str(e)}",
                    (start_dt, end_dt),
                    e,
                )
                if (
                    checkpoint.cached_site_descriptors
                    and len(checkpoint.cached_site_descriptors) > 0
                ):
                    checkpoint.current_site_descriptor = (
                        checkpoint.cached_site_descriptors.popleft()
                    )
                    checkpoint.cached_drives = None
                    # The next site's drives point at its node as their parent.
                    yield from self._yield_site_hierarchy_node(
                        checkpoint.current_site_descriptor,
                        checkpoint,
                        include_permissions=include_permissions,
                    )
                    return checkpoint
                else:
                    checkpoint.has_more = False
                    return checkpoint

            return checkpoint

        if (
            checkpoint.current_site_descriptor
            and checkpoint.cached_drives
            and checkpoint.current_drive is None
        ):
            checkpoint.current_drive = checkpoint.cached_drives.popleft()

            start_dt = datetime.fromtimestamp(start, tz=timezone.utc)
            end_dt = datetime.fromtimestamp(end, tz=timezone.utc)
            site_descriptor = checkpoint.current_site_descriptor

            logger.info(
                "Processing drive '%s' in site: %s",
                checkpoint.current_drive.display_name,
                site_descriptor.url,
            )
            logger.debug("Time range: %s to %s", start_dt, end_dt)

            try:
                if site_descriptor.folder_path:
                    checkpoint.current_folder = self.ops.resolve_folder(
                        drive_id=checkpoint.current_drive.drive_id,
                        folder_path=site_descriptor.folder_path,
                    )
                yield from self._yield_drive_hierarchy_node(
                    site_descriptor.url,
                    checkpoint.current_drive,
                    checkpoint,
                    include_permissions=include_permissions,
                )
            except Exception as e:
                logger.error(
                    "Failed to retrieve items from drive '%s' in site: %s: %s",
                    checkpoint.current_drive.display_name,
                    site_descriptor.url,
                    e,
                )
                yield _create_entity_failure(
                    checkpoint.current_drive.drive_id,
                    f"Failed to access drive '{checkpoint.current_drive.display_name}' "
                    f"in site '{site_descriptor.url}': {str(e)}",
                    (start_dt, end_dt),
                    e,
                )
                self._clear_drive_checkpoint_state(checkpoint)
                return checkpoint

            if not site_descriptor.folder_path:
                checkpoint.current_drive_delta_next_link = build_delta_start_url(
                    self.graph_api_base,
                    checkpoint.current_drive.drive_id,
                    start_dt,
                )
        if checkpoint.current_site_descriptor and checkpoint.current_drive is not None:
            site_descriptor = checkpoint.current_site_descriptor
            start_dt = datetime.fromtimestamp(start, tz=timezone.utc)
            end_dt = datetime.fromtimestamp(end, tz=timezone.utc)
            current_drive = checkpoint.current_drive

            # --- determine item source ---
            driveitems: Iterable[DriveItemData]
            has_more_delta_pages = False

            if checkpoint.current_drive_delta_next_link:
                try:
                    result = self.ops.get_delta_page(
                        drive_id=current_drive.drive_id,
                        page_url=checkpoint.current_drive_delta_next_link,
                        allow_full_resync=not (
                            checkpoint.current_drive_delta_resync_attempted
                        ),
                    )
                except Exception as e:
                    logger.error(
                        "Failed to fetch delta page for drive '%s': %s",
                        current_drive.display_name,
                        e,
                    )
                    yield _create_entity_failure(
                        current_drive.drive_id,
                        f"Failed to fetch delta page for drive "
                        f"'{current_drive.display_name}': {str(e)}",
                        (start_dt, end_dt),
                        e,
                    )
                    self._clear_drive_checkpoint_state(checkpoint)
                    return checkpoint

                if result.resync_after_410:
                    checkpoint.current_drive_delta_resync_attempted = True
                driveitems = iter_delta_page_files(result.page, start_dt, end_dt)
                has_more_delta_pages = result.next_checkpoint_url is not None
                checkpoint.current_drive_delta_next_link = result.next_checkpoint_url
            else:
                driveitems = self.ops.iter_folder_items(
                    drive_id=current_drive.drive_id,
                    folder_id=(
                        checkpoint.current_folder.id
                        if checkpoint.current_folder
                        else None
                    ),
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
                        current_drive,
                        site_descriptor.url,
                        checkpoint,
                        include_permissions,
                    )
            except Exception as e:
                logger.exception(
                    "Failed mid-iteration for drive '%s' in site '%s'",
                    current_drive.display_name,
                    site_descriptor.url,
                )
                yield _create_entity_failure(
                    f"{current_drive.drive_id}|bfs_iter",
                    f"Failed to iterate drive items after {item_count}: {e}",
                    (start_dt, end_dt),
                    e,
                )
                # Clear drive state to avoid resuming on the same broken drive.
                self._clear_drive_checkpoint_state(checkpoint)
                return checkpoint

            logger.info(
                "Processed %s items in drive '%s'",
                item_count,
                current_drive.display_name,
            )

            if has_more_delta_pages:
                return checkpoint

            self._clear_drive_checkpoint_state(checkpoint)

        # Phase 4: Progression logic - determine next step
        # If we have more drives in current site, continue with current site
        if checkpoint.cached_drives:
            logger.debug(
                "Continuing with %s remaining drives in current site",
                len(checkpoint.cached_drives),
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
                        yield (
                            _convert_sitepage_to_document(
                                site_page,
                                site_descriptor.drive_name,
                                self.ops,
                                site_descriptor.url,
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
                if isinstance(e, MicrosoftGraphError):
                    logger.warning(
                        "Skipping site pages for %s: Graph returned %s (%s)",
                        site_descriptor.url,
                        e.status,
                        e.code,
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
            checkpoint.cached_drives = None
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
        ``extract_site_descriptors``, list its drives, and probe each by item
        id until one resolves — all under the existing ``Sites.Read.All`` grant.
        ``site_drives_cache`` memoizes the per-site drive listing since targets
        cluster heavily by site. Raises ``ValueError`` if no drive resolves it.
        """
        descriptors = extract_site_descriptors([document_link])
        if not descriptors:
            raise ValueError(f"Could not parse a site from link '{document_link}'")
        site_url = descriptors[0].url

        for drive in self._get_drives_for_site(site_url, site_drives_cache):
            driveitem = self.ops.get_drive_item(
                drive_id=drive.drive_id, item_id=document_id
            )
            if driveitem is None:
                continue
            return ResolvedDriveItem(
                driveitem=driveitem, drive=drive, site_url=site_url
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
        yield from self._yield_drive_hierarchy_node(
            resolved.site_url,
            resolved.drive,
            dedup,
            include_permissions=include_permissions,
        )
        yield from self._process_drive_item(
            resolved.driveitem,
            resolved.drive,
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
        descriptors = extract_site_descriptors([document_link])
        if not descriptors:
            raise ValueError(
                f"Could not parse a site from site-page link '{document_link}'"
            )
        site_descriptor = SiteDescriptor(
            url=descriptors[0].url, drive_name=None, folder_path=None
        )
        site_id = self.ops.get_site_id(site_url=site_descriptor.url)

        page = self._fetch_single_site_page(site_id, document_id)

        yield from self._yield_site_hierarchy_node(
            site_descriptor,
            dedup,
            include_permissions=include_permissions,
        )

        yield _convert_sitepage_to_document(
            page,
            site_descriptor.drive_name,
            self.ops,
            site_descriptor.url,
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
        if self._ops is None:
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
