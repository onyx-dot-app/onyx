import base64
import copy
import html
import io
import os
import re
import time
from collections import deque
from collections.abc import Generator
from collections.abc import Iterable
from datetime import datetime
from datetime import timezone
from enum import Enum
from typing import Any
from typing import cast
from urllib.parse import quote
from urllib.parse import unquote
from urllib.parse import urlsplit

import msal  # type: ignore[import-untyped]
import requests
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.serialization import pkcs12
from office365.graph_client import GraphClient  # type: ignore[import-untyped]
from office365.intune.organizations.organization import Organization  # type: ignore[import-untyped]
from office365.onedrive.driveitems.driveItem import DriveItem  # type: ignore[import-untyped]
from office365.onedrive.sites.site import Site  # type: ignore[import-untyped]
from office365.onedrive.sites.sites_with_root import SitesWithRoot  # type: ignore[import-untyped]
from office365.runtime.auth.token_response import TokenResponse  # type: ignore[import-untyped]
from office365.runtime.client_request import ClientRequestException  # type: ignore
from office365.runtime.paths.resource_path import ResourcePath  # type: ignore[import-untyped]
from office365.runtime.queries.client_query import ClientQuery  # type: ignore[import-untyped]
from office365.sharepoint.client_context import ClientContext  # type: ignore[import-untyped]
from pydantic import BaseModel
from pydantic import Field

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.configs.app_configs import REQUEST_TIMEOUT_SECONDS
from onyx.configs.app_configs import SHAREPOINT_CONNECTOR_SIZE_THRESHOLD
from onyx.configs.constants import DocumentSource
from onyx.configs.constants import FileOrigin
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.interfaces import CheckpointedConnectorWithPermSync
from onyx.connectors.interfaces import CheckpointOutput
from onyx.connectors.interfaces import GenerateSlimDocumentOutput
from onyx.connectors.interfaces import IndexingHeartbeatInterface
from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.interfaces import SlimConnectorWithPermSync
from onyx.connectors.microsoft_graph_env import resolve_microsoft_environment
from onyx.connectors.models import BasicExpertInfo
from onyx.connectors.models import ConnectorCheckpoint
from onyx.connectors.models import ConnectorFailure
from onyx.connectors.models import ConnectorMissingCredentialError
from onyx.connectors.models import Document
from onyx.connectors.models import DocumentFailure
from onyx.connectors.models import EntityFailure
from onyx.connectors.models import ExternalAccess
from onyx.connectors.models import HierarchyNode
from onyx.connectors.models import ImageSection
from onyx.connectors.models import SlimDocument
from onyx.connectors.models import TextSection
from onyx.connectors.sharepoint.connector_utils import get_sharepoint_external_access
from onyx.db.enums import HierarchyNodeType
from onyx.file_processing.extract_file_text import extract_text_and_images
from onyx.file_processing.extract_file_text import get_file_ext
from onyx.file_processing.file_types import OnyxFileExtensions
from onyx.file_processing.file_types import OnyxMimeTypes
from onyx.file_processing.image_utils import store_image_and_create_section
from onyx.utils.b64 import get_image_type_from_bytes
from onyx.utils.logger import setup_logger

logger = setup_logger()
SLIM_BATCH_SIZE = 1000
_EPOCH = datetime.fromtimestamp(0, tz=timezone.utc)


SHARED_DOCUMENTS_MAP = {
    "Documents": "Shared Documents",
    "Dokumente": "Freigegebene Dokumente",
    "Documentos": "Documentos compartidos",
}
SHARED_DOCUMENTS_MAP_REVERSE = {v: k for k, v in SHARED_DOCUMENTS_MAP.items()}

ASPX_EXTENSION = ".aspx"

DEFAULT_AUTHORITY_HOST = "https://login.microsoftonline.com"
DEFAULT_GRAPH_API_HOST = "https://graph.microsoft.com"
DEFAULT_SHAREPOINT_DOMAIN_SUFFIX = "sharepoint.com"

GRAPH_API_BASE = f"{DEFAULT_GRAPH_API_HOST}/v1.0"
GRAPH_API_MAX_RETRIES = 5
GRAPH_API_RETRYABLE_STATUSES = frozenset({429, 500, 502, 503, 504})


class DriveItemData(BaseModel):
    """Lightweight representation of a Graph API drive item, parsed from JSON.

    Replaces the SDK DriveItem for fetching/listing so that we can paginate
    lazily through the Graph API without materialising every item in memory.
    """

    id: str
    name: str
    web_url: str
    size: int | None = None
    mime_type: str | None = None
    download_url: str | None = None
    last_modified_datetime: datetime | None = None
    last_modified_by_display_name: str | None = None
    last_modified_by_email: str | None = None
    parent_reference_path: str | None = None
    drive_id: str | None = None

    @classmethod
    def from_graph_json(cls, item: dict[str, Any]) -> "DriveItemData":
        last_mod_raw = item.get("lastModifiedDateTime")
        last_mod: datetime | None = None
        if isinstance(last_mod_raw, str):
            last_mod = datetime.fromisoformat(last_mod_raw.replace("Z", "+00:00"))

        last_modified_by = item.get("lastModifiedBy", {}).get("user", {})
        parent_ref = item.get("parentReference", {})

        return cls(
            id=item["id"],
            name=item.get("name", ""),
            web_url=item.get("webUrl", ""),
            size=item.get("size"),
            mime_type=item.get("file", {}).get("mimeType"),
            download_url=item.get("@microsoft.graph.downloadUrl"),
            last_modified_datetime=last_mod,
            last_modified_by_display_name=last_modified_by.get("displayName"),
            last_modified_by_email=(
                last_modified_by.get("email")
                or last_modified_by.get("userPrincipalName")
            ),
            parent_reference_path=parent_ref.get("path"),
            drive_id=parent_ref.get("driveId"),
        )

    def to_sdk_driveitem(self, graph_client: GraphClient) -> DriveItem:
        """Construct a lazy SDK DriveItem for permission lookups."""
        if not self.drive_id:
            raise ValueError("drive_id is required to construct SDK DriveItem")
        path = ResourcePath(
            self.id,
            ResourcePath("items", ResourcePath(self.drive_id, ResourcePath("drives"))),
        )
        item = DriveItem(graph_client, path)
        item.set_property("id", self.id)
        return item


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


class CertificateData(BaseModel):
    """Data class for storing certificate information loaded from PFX file."""

    private_key: bytes
    thumbprint: str


def _site_page_in_time_window(
    page: dict[str, Any],
    start: datetime | None,
    end: datetime | None,
) -> bool:
    """Return True if the page's lastModifiedDateTime falls within [start, end]."""
    if start is None and end is None:
        return True
    raw = page.get("lastModifiedDateTime")
    if not raw:
        return True
    if not isinstance(raw, str):
        raise ValueError(f"lastModifiedDateTime is not a string: {raw}")
    last_modified = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    return (start is None or last_modified >= start) and (
        end is None or last_modified <= end
    )


def sleep_and_retry(
    query_obj: ClientQuery, method_name: str, max_retries: int = 3
) -> Any:
    """
    Execute a SharePoint query with retry logic for rate limiting.
    """
    for attempt in range(max_retries + 1):
        try:
            return query_obj.execute_query()
        except ClientRequestException as e:
            status = e.response.status_code if e.response is not None else None

            # 429 / 503 — rate limit or transient error.  Back off and retry.
            if status in (429, 503) and attempt < max_retries:
                logger.warning(
                    f"Rate limit exceeded on {method_name}, attempt {attempt + 1}/{max_retries + 1}, sleeping and retrying"
                )
                retry_after = e.response.headers.get("Retry-After")
                if retry_after:
                    sleep_time = int(retry_after)
                else:
                    # Exponential backoff: 2^attempt * 5 seconds
                    sleep_time = min(30, (2**attempt) * 5)

                logger.info(f"Sleeping for {sleep_time} seconds before retry")
                time.sleep(sleep_time)
                continue

            # Non-retryable error or retries exhausted — log details and raise.
            if e.response is not None:
                logger.error(
                    f"SharePoint request failed for {method_name}: "
                    f"status={status}, "
                )
            raise e


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


class SharepointAuthMethod(Enum):
    CLIENT_SECRET = "client_secret"
    CERTIFICATE = "certificate"


class SizeCapExceeded(Exception):
    """Exception raised when the size cap is exceeded."""


def load_certificate_from_pfx(pfx_data: bytes, password: str) -> CertificateData | None:
    """Load certificate from .pfx file for MSAL authentication"""
    try:
        # Load the certificate and private key
        private_key, certificate, additional_certificates = (
            pkcs12.load_key_and_certificates(pfx_data, password.encode("utf-8"))
        )

        # Validate that certificate and private key are not None
        if certificate is None or private_key is None:
            raise ValueError("Certificate or private key is None")

        # Convert to PEM format that MSAL expects
        key_pem = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )

        return CertificateData(
            private_key=key_pem,
            thumbprint=certificate.fingerprint(hashes.SHA1()).hex(),
        )
    except Exception as e:
        logger.error(f"Error loading certificate: {e}")
        return None


def acquire_token_for_rest(
    msal_app: msal.ConfidentialClientApplication,
    sp_tenant_domain: str,
    sharepoint_domain_suffix: str,
) -> TokenResponse:
    token = msal_app.acquire_token_for_client(
        scopes=[f"https://{sp_tenant_domain}.{sharepoint_domain_suffix}/.default"]
    )
    return TokenResponse.from_json(token)


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


def _probe_remote_size(url: str, timeout: int) -> int | None:
    """Determine remote size using HEAD or a range GET probe. Returns None if unknown."""
    try:
        head_resp = requests.head(url, timeout=timeout, allow_redirects=True)
        head_resp.raise_for_status()
        cl = head_resp.headers.get("Content-Length")
        if cl and cl.isdigit():
            return int(cl)
    except requests.RequestException:
        pass

    # Fallback: Range request for first byte to read total from Content-Range
    try:
        with requests.get(
            url,
            headers={"Range": "bytes=0-0"},
            timeout=timeout,
            stream=True,
        ) as range_resp:
            range_resp.raise_for_status()
            cr = range_resp.headers.get("Content-Range")  # e.g., "bytes 0-0/12345"
            if cr and "/" in cr:
                total = cr.split("/")[-1]
                if total.isdigit():
                    return int(total)
    except requests.RequestException:
        pass

    # If both HEAD and a range GET failed to reveal a size, signal unknown size.
    # Callers should treat None as "size unavailable" and proceed with a safe
    # streaming path that enforces a hard cap to avoid excessive memory usage.
    return None


def _download_with_cap(url: str, timeout: int, cap: int) -> bytes:
    """Stream download content with an upper bound on bytes read.

    Behavior:
    - Checks `Content-Length` first and aborts early if it exceeds `cap`.
    - Otherwise streams the body in chunks and stops once `cap` is surpassed.
    - Raises `SizeCapExceeded` when the cap would be exceeded.
    - Returns the full bytes if the content fits within `cap`.
    """
    with requests.get(url, stream=True, timeout=timeout) as resp:
        resp.raise_for_status()

        # If the server provides Content-Length, prefer an early decision.
        cl_header = resp.headers.get("Content-Length")
        if cl_header and cl_header.isdigit():
            content_len = int(cl_header)
            if content_len > cap:
                logger.warning(
                    f"Content-Length {content_len} exceeds cap {cap}; skipping download."
                )
                raise SizeCapExceeded("pre_download")

        buf = io.BytesIO()
        # Stream in 64KB chunks; adjust if needed for slower networks.
        for chunk in resp.iter_content(64 * 1024):
            if not chunk:
                continue
            buf.write(chunk)
            if buf.tell() > cap:
                # Avoid keeping a large partial buffer; close and signal caller to skip.
                logger.warning(
                    f"Streaming download exceeded cap {cap} bytes; aborting early."
                )
                raise SizeCapExceeded("during_download")

        return buf.getvalue()


def _download_via_graph_api(
    access_token: str,
    drive_id: str,
    item_id: str,
    bytes_allowed: int,
    graph_api_base: str,
) -> bytes:
    """Download a drive item via the Graph API /content endpoint with a byte cap.

    Raises SizeCapExceeded if the cap is exceeded.
    """
    url = f"{graph_api_base}/drives/{drive_id}/items/{item_id}/content"
    headers = {"Authorization": f"Bearer {access_token}"}
    with requests.get(
        url, headers=headers, stream=True, timeout=REQUEST_TIMEOUT_SECONDS
    ) as resp:
        resp.raise_for_status()
        buf = io.BytesIO()
        for chunk in resp.iter_content(64 * 1024):
            if not chunk:
                continue
            buf.write(chunk)
            if buf.tell() > bytes_allowed:
                raise SizeCapExceeded("during_graph_api_download")
        return buf.getvalue()


def _convert_driveitem_to_document_with_permissions(
    driveitem: DriveItemData,
    drive_name: str,
    ctx: ClientContext | None,
    graph_client: GraphClient,
    graph_api_base: str,
    include_permissions: bool = False,
    parent_hierarchy_raw_node_id: str | None = None,
    access_token: str | None = None,
) -> Document | ConnectorFailure | None:

    if not driveitem.name or not driveitem.id:
        raise ValueError("DriveItem name/id is required")

    if include_permissions and ctx is None:
        raise ValueError("ClientContext is required for permissions")

    mime_type = driveitem.mime_type
    if not mime_type or mime_type in OnyxMimeTypes.EXCLUDED_IMAGE_TYPES:
        logger.debug(
            f"Skipping malformed or excluded mime type {mime_type} for {driveitem.name}"
        )
        return None

    file_size = driveitem.size
    download_url = driveitem.download_url

    if file_size is None and download_url:
        file_size = _probe_remote_size(download_url, REQUEST_TIMEOUT_SECONDS)

    if file_size is not None and file_size > SHAREPOINT_CONNECTOR_SIZE_THRESHOLD:
        logger.warning(
            f"Skipping '{driveitem.name}' over size threshold ({file_size} > {SHAREPOINT_CONNECTOR_SIZE_THRESHOLD} bytes)."
        )
        return None

    # Prefer downloadUrl streaming with size cap
    content_bytes: bytes | None = None
    if download_url:
        try:
            content_bytes = _download_with_cap(
                download_url,
                REQUEST_TIMEOUT_SECONDS,
                SHAREPOINT_CONNECTOR_SIZE_THRESHOLD,
            )
        except SizeCapExceeded as e:
            logger.warning(f"Skipping '{driveitem.name}' exceeded size cap: {str(e)}")
            return None
        except requests.RequestException as e:
            status = e.response.status_code if e.response is not None else -1
            logger.warning(
                f"Failed to download via downloadUrl for '{driveitem.name}' (status={status}); falling back to Graph API."
            )

    # Fallback: download via Graph API /content endpoint
    if content_bytes is None and access_token and driveitem.drive_id:
        try:
            content_bytes = _download_via_graph_api(
                access_token,
                driveitem.drive_id,
                driveitem.id,
                SHAREPOINT_CONNECTOR_SIZE_THRESHOLD,
                graph_api_base=graph_api_base,
            )
        except SizeCapExceeded:
            logger.warning(
                f"Skipping '{driveitem.name}' exceeded size cap during Graph API download."
            )
            return None
        except Exception as e:
            logger.warning(
                f"Failed to download via Graph API for '{driveitem.name}': {e}"
            )
            return _create_document_failure(
                driveitem, f"Failed to download via graph api: {e}", e
            )

    sections: list[TextSection | ImageSection] = []
    file_ext = get_file_ext(driveitem.name)

    if not content_bytes:
        logger.warning(
            f"Zero-length content for '{driveitem.name}'. Skipping text/image extraction."
        )
    elif file_ext in OnyxFileExtensions.IMAGE_EXTENSIONS:
        image_section, _ = store_image_and_create_section(
            image_data=content_bytes,
            file_id=driveitem.id,
            display_name=driveitem.name,
            file_origin=FileOrigin.CONNECTOR,
        )
        image_section.link = driveitem.web_url
        sections.append(image_section)
    else:

        def _store_embedded_image(img_data: bytes, img_name: str) -> None:
            try:
                img_mime = get_image_type_from_bytes(img_data)
            except ValueError:
                logger.debug(
                    "Skipping embedded image with unknown format for %s",
                    driveitem.name,
                )
                return

            if img_mime in OnyxMimeTypes.EXCLUDED_IMAGE_TYPES:
                logger.debug(
                    "Skipping embedded image of excluded type %s for %s",
                    img_mime,
                    driveitem.name,
                )
                return

            image_section, _ = store_image_and_create_section(
                image_data=img_data,
                file_id=f"{driveitem.id}_img_{len(sections)}",
                display_name=img_name or f"{driveitem.name} - image {len(sections)}",
                file_origin=FileOrigin.CONNECTOR,
            )
            image_section.link = driveitem.web_url
            sections.append(image_section)

        extraction_result = extract_text_and_images(
            file=io.BytesIO(content_bytes),
            file_name=driveitem.name,
            image_callback=_store_embedded_image,
        )
        if extraction_result.text_content:
            sections.append(
                TextSection(link=driveitem.web_url, text=extraction_result.text_content)
            )

    if include_permissions and ctx is not None:
        logger.info(f"Getting external access for {driveitem.name}")
        sdk_item = driveitem.to_sdk_driveitem(graph_client)
        external_access = get_sharepoint_external_access(
            ctx=ctx,
            graph_client=graph_client,
            drive_item=sdk_item,
            drive_name=drive_name,
            add_prefix=True,
        )
    else:
        external_access = ExternalAccess.empty()

    doc = Document(
        id=driveitem.id,
        sections=sections,
        source=DocumentSource.SHAREPOINT,
        semantic_identifier=driveitem.name,
        external_access=external_access,
        doc_updated_at=(
            driveitem.last_modified_datetime.replace(tzinfo=timezone.utc)
            if driveitem.last_modified_datetime
            else None
        ),
        primary_owners=[
            BasicExpertInfo(
                display_name=driveitem.last_modified_by_display_name or "",
                email=driveitem.last_modified_by_email or "",
            )
        ],
        metadata={"drive": drive_name},
        parent_hierarchy_raw_node_id=parent_hierarchy_raw_node_id,
    )
    return doc


def _convert_sitepage_to_document(
    site_page: dict[str, Any],
    site_name: str | None,
    ctx: ClientContext | None,
    graph_client: GraphClient,
    include_permissions: bool = False,
    parent_hierarchy_raw_node_id: str | None = None,
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

    # Parse creation and modification info
    created_datetime = site_page.get("createdDateTime")
    if created_datetime:
        if isinstance(created_datetime, str):
            created_datetime = datetime.fromisoformat(
                created_datetime.replace("Z", "+00:00")
            )
        elif not created_datetime.tzinfo:
            created_datetime = created_datetime.replace(tzinfo=timezone.utc)

    last_modified_datetime = site_page.get("lastModifiedDateTime")
    if last_modified_datetime:
        if isinstance(last_modified_datetime, str):
            last_modified_datetime = datetime.fromisoformat(
                last_modified_datetime.replace("Z", "+00:00")
            )
        elif not last_modified_datetime.tzinfo:
            last_modified_datetime = last_modified_datetime.replace(tzinfo=timezone.utc)

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
            ctx=ctx,
            graph_client=graph_client,
            site_page=site_page,
            add_prefix=True,
        )
    else:
        external_access = ExternalAccess.empty()

    doc = Document(
        id=site_page["id"],
        sections=[TextSection(link=web_url, text=page_text)],
        source=DocumentSource.SHAREPOINT,
        external_access=external_access,
        semantic_identifier=semantic_identifier,
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
) -> SlimDocument:
    if driveitem.id is None:
        raise ValueError("DriveItem ID is required")

    sdk_item = driveitem.to_sdk_driveitem(graph_client)
    external_access = get_sharepoint_external_access(
        ctx=ctx,
        graph_client=graph_client,
        drive_item=sdk_item,
        drive_name=drive_name,
    )

    return SlimDocument(
        id=driveitem.id,
        external_access=external_access,
    )


def _convert_sitepage_to_slim_document(
    site_page: dict[str, Any], ctx: ClientContext | None, graph_client: GraphClient
) -> SlimDocument:
    """Convert a SharePoint site page to a SlimDocument object."""
    if site_page.get("id") is None:
        raise ValueError("Site page ID is required")

    external_access = get_sharepoint_external_access(
        ctx=ctx,
        graph_client=graph_client,
        site_page=site_page,
    )
    id = site_page.get("id")
    if id is None:
        raise ValueError("Site page ID is required")
    return SlimDocument(
        id=id,
        external_access=external_access,
    )


class SharepointConnector(
    SlimConnectorWithPermSync,
    CheckpointedConnectorWithPermSync[SharepointConnectorCheckpoint],
):
    def __init__(
        self,
        batch_size: int = INDEX_BATCH_SIZE,
        sites: list[str] = [],
        include_site_pages: bool = True,
        include_site_documents: bool = True,
        authority_host: str = DEFAULT_AUTHORITY_HOST,
        graph_api_host: str = DEFAULT_GRAPH_API_HOST,
        sharepoint_domain_suffix: str = DEFAULT_SHAREPOINT_DOMAIN_SUFFIX,
    ) -> None:
        self.batch_size = batch_size
        self.sites = list(sites)
        self.site_descriptors: list[SiteDescriptor] = self._extract_site_and_drive_info(
            sites
        )
        self._graph_client: GraphClient | None = None
        self.msal_app: msal.ConfidentialClientApplication | None = None
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
                f"Configured sharepoint_domain_suffix '{sharepoint_domain_suffix}' "
                f"differs from the expected suffix '{resolved_env.sharepoint_domain_suffix}' "
                f"for the {resolved_env.environment} environment. "
                f"Using '{resolved_env.sharepoint_domain_suffix}'."
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
                "/sites/" in site_url or "/teams/" in site_url
            ):
                raise ConnectorValidationError(
                    "Site URLs must be full Sharepoint URLs (e.g. https://your-tenant.sharepoint.com/sites/your-site or https://your-tenant.sharepoint.com/teams/your-team)"
                )

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
                "Rebuilding SharePoint REST client context "
                "(elapsed=%.0fs, site_changed=%s)",
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
            logger.warning(f"Sharepoint URL '{url}' could not be parsed")
            return None, []

        if not parsed.scheme or not parsed.netloc:
            logger.warning(
                f"Sharepoint URL '{url}' is not a valid absolute URL (missing scheme or host)"
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
            for site_token in ("sites", "teams"):
                if site_token in lower_parts:
                    site_type_index = lower_parts.index(site_token)
                    break

            if site_type_index is None or len(parts) <= site_type_index + 1:
                logger.warning(
                    f"Site URL '{url}' is not a valid Sharepoint URL (must contain /sites/<name> or /teams/<name>)"
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
        logger.info(f"Found drives: {[d.name for d in drives]}")

        matched = [
            d
            for d in drives
            if (d.name and d.name.lower() == drive_name.lower())
            or (
                d.name in SHARED_DOCUMENTS_MAP
                and SHARED_DOCUMENTS_MAP[d.name] == drive_name
            )
        ]
        if not matched:
            logger.warning(f"Drive '{drive_name}' not found")
            return None

        drive = matched[0]
        drive_web_url: str | None = drive.web_url
        logger.info(f"Found drive: {drive.name} (web_url: {drive_web_url})")
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
                yield from self._iter_drive_items_paged(
                    drive_id=drive_id,
                    folder_path=site_descriptor.folder_path,
                    start=start,
                    end=end,
                )
            else:
                yield from self._iter_drive_items_delta(
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

            logger.warning(f"Failed to process site: {site_descriptor.url} - {err_str}")

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
            logger.debug(f"Found drives: {[d.name for d in drives]}")

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
                    logger.warning(f"Drive '{site_descriptor.drive_name}' not found")
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
                        item_iter = self._iter_drive_items_paged(
                            drive_id=cast(str, drive.id),
                            folder_path=site_descriptor.folder_path,
                            start=start,
                            end=end,
                        )
                    else:
                        item_iter = self._iter_drive_items_delta(
                            drive_id=cast(str, drive.id),
                            start=start,
                            end=end,
                        )

                    for item in item_iter:
                        yield item, drive_name or "", drive_web_url

                except Exception as e:
                    logger.warning(f"Failed to process drive '{drive.name}': {str(e)}")

        except Exception as e:
            err_str = str(e)
            if (
                "403 Client Error" in err_str
                or "404 Client Error" in err_str
                or "invalid_client" in err_str
            ):
                raise e

            logger.warning(f"Failed to process site: {err_str}")

    def _handle_paginated_sites(
        self, sites: SitesWithRoot
    ) -> Generator[Site, None, None]:
        while sites:
            if sites.current_page:
                yield from sites.current_page
            if not sites.has_next:
                break
            sites = sites._get_next().execute_query()

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
        return site_descriptors

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

        page_url: str | None = (
            f"{self.graph_api_base}/sites/{site_id}" f"/pages/microsoft.graph.sitePage"
        )
        params: dict[str, str] | None = {"$expand": "canvasLayout"}
        total_yielded = 0

        while page_url:
            data = self._graph_api_get_json(page_url, params)
            params = None  # nextLink already embeds query params

            for page in data.get("value", []):
                if not _site_page_in_time_window(page, start, end):
                    continue
                total_yielded += 1
                yield page

            page_url = data.get("@odata.nextLink")

        logger.debug(f"Yielded {total_yielded} site pages for {site_descriptor.url}")

    def _acquire_token(self) -> dict[str, Any]:
        """
        Acquire token via MSAL
        """
        if self.msal_app is None:
            raise RuntimeError("MSAL app is not initialized")

        token = self.msal_app.acquire_token_for_client(
            scopes=[f"{self.graph_api_host}/.default"]
        )
        return token

    def _get_graph_access_token(self) -> str:
        token_data = self._acquire_token()
        access_token = token_data.get("access_token")
        if not access_token:
            raise RuntimeError("Failed to acquire Graph API access token")
        return access_token

    def _graph_api_get_json(
        self,
        url: str,
        params: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Make an authenticated GET request to the Graph API with retry."""
        access_token = self._get_graph_access_token()
        headers = {"Authorization": f"Bearer {access_token}"}

        for attempt in range(GRAPH_API_MAX_RETRIES + 1):
            try:
                response = requests.get(
                    url,
                    headers=headers,
                    params=params,
                    timeout=REQUEST_TIMEOUT_SECONDS,
                )
                if response.status_code in GRAPH_API_RETRYABLE_STATUSES:
                    if attempt < GRAPH_API_MAX_RETRIES:
                        retry_after = int(
                            response.headers.get("Retry-After", str(2**attempt))
                        )
                        wait = min(retry_after, 60)
                        logger.warning(
                            f"Graph API {response.status_code} on attempt {attempt + 1}, "
                            f"retrying in {wait}s: {url}"
                        )
                        time.sleep(wait)
                        # Re-acquire token in case it expired during a long traversal
                        access_token = self._get_graph_access_token()
                        headers = {"Authorization": f"Bearer {access_token}"}
                        continue
                response.raise_for_status()
                return response.json()
            except (requests.ConnectionError, requests.Timeout):
                if attempt < GRAPH_API_MAX_RETRIES:
                    wait = min(2**attempt, 60)
                    logger.warning(
                        f"Graph API connection error on attempt {attempt + 1}, "
                        f"retrying in {wait}s: {url}"
                    )
                    time.sleep(wait)
                    continue
                raise

        raise RuntimeError(
            f"Graph API request failed after {GRAPH_API_MAX_RETRIES + 1} attempts: {url}"
        )

    def _iter_drive_items_paged(
        self,
        drive_id: str,
        folder_path: str | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
        page_size: int = 200,
    ) -> Generator[DriveItemData, None, None]:
        """Yield DriveItemData for every file in a drive via the Graph API.

        Performs BFS folder traversal manually, fetching one page of children
        at a time so that memory usage stays bounded regardless of drive size.
        """
        base = f"{self.graph_api_base}/drives/{drive_id}"
        if folder_path:
            encoded_path = quote(folder_path, safe="/")
            start_url = f"{base}/root:/{encoded_path}:/children"
        else:
            start_url = f"{base}/root/children"

        folder_queue: deque[str] = deque([start_url])

        while folder_queue:
            page_url: str | None = folder_queue.popleft()
            params: dict[str, str] | None = {"$top": str(page_size)}

            while page_url:
                data = self._graph_api_get_json(page_url, params)
                params = None  # nextLink already embeds query params

                for item in data.get("value", []):
                    if "folder" in item:
                        child_url = f"{base}/items/{item['id']}/children"
                        folder_queue.append(child_url)
                        continue

                    # Skip non-file items (e.g. OneNote notebooks without a "file" facet)
                    # but still yield them — the downstream conversion handles filtering
                    # by extension / mime type.

                    # NOTE: We are now including items without a lastModifiedDateTime,
                    # and respecting when only one of start or end is set.
                    if start is not None or end is not None:
                        raw_ts = item.get("lastModifiedDateTime")
                        if raw_ts:
                            mod_dt = datetime.fromisoformat(
                                raw_ts.replace("Z", "+00:00")
                            )
                            if start is not None and mod_dt < start:
                                continue
                            if end is not None and mod_dt > end:
                                continue

                    yield DriveItemData.from_graph_json(item)

                page_url = data.get("@odata.nextLink")

    def _iter_drive_items_delta(
        self,
        drive_id: str,
        start: datetime | None = None,
        end: datetime | None = None,
        page_size: int = 200,
    ) -> Generator[DriveItemData, None, None]:
        """Yield DriveItemData for every file in a drive via the Graph delta API.

        Uses the flat delta endpoint instead of recursive folder traversal.
        On subsequent runs (start > epoch), passes the start timestamp as a
        delta token so that only changed items are returned.

        Falls back to full enumeration if the API returns 410 Gone (expired token).
        """
        use_timestamp_token = start is not None and start > _EPOCH

        initial_url = f"{self.graph_api_base}/drives/{drive_id}/root/delta"
        if use_timestamp_token:
            assert start is not None  # mypy
            token = quote(start.isoformat(timespec="seconds"))
            initial_url += f"?token={token}"

        yield from self._iter_delta_pages(
            initial_url=initial_url,
            drive_id=drive_id,
            start=start,
            end=end,
            page_size=page_size,
            allow_full_resync=use_timestamp_token,
        )

    def _iter_delta_pages(
        self,
        initial_url: str,
        drive_id: str,
        start: datetime | None,
        end: datetime | None,
        page_size: int,
        allow_full_resync: bool,
    ) -> Generator[DriveItemData, None, None]:
        """Paginate through delta API responses, yielding file DriveItemData.

        If the API responds with 410 Gone and allow_full_resync is True,
        restarts with a full delta enumeration.
        """
        page_url: str | None = initial_url
        params: dict[str, str] | None = {"$top": str(page_size)}

        while page_url:
            try:
                data = self._graph_api_get_json(page_url, params)
            except requests.HTTPError as e:
                # 410 means the delta token expired, so we need to fall back to full enumeration
                if e.response is not None and e.response.status_code == 410:
                    if not allow_full_resync:
                        raise
                    logger.warning(
                        "Delta token expired (410 Gone) for drive '%s'. "
                        "Falling back to full delta enumeration.",
                        drive_id,
                    )
                    yield from self._iter_delta_pages(
                        initial_url=f"{self.graph_api_base}/drives/{drive_id}/root/delta",
                        drive_id=drive_id,
                        start=start,
                        end=end,
                        page_size=page_size,
                        allow_full_resync=False,
                    )
                    return
                raise

            params = None  # nextLink/deltaLink already embed query params

            for item in data.get("value", []):
                if "folder" in item or "deleted" in item:
                    continue

                if start is not None or end is not None:
                    raw_ts = item.get("lastModifiedDateTime")
                    if raw_ts:
                        mod_dt = datetime.fromisoformat(raw_ts.replace("Z", "+00:00"))
                        if start is not None and mod_dt < start:
                            continue
                        if end is not None and mod_dt > end:
                            continue

                yield DriveItemData.from_graph_json(item)

            page_url = data.get("@odata.nextLink")
            if not page_url:
                break

    def _build_delta_start_url(
        self,
        drive_id: str,
        start: datetime | None = None,
        page_size: int = 200,
    ) -> str:
        """Build the initial delta API URL with query parameters embedded.

        Embeds ``$top`` (and optionally a timestamp ``token``) directly in the
        URL so that the returned string is fully self-contained and can be
        stored in a checkpoint without needing a separate params dict.
        """
        base_url = f"{self.graph_api_base}/drives/{drive_id}/root/delta"
        params = [f"$top={page_size}"]
        if start is not None and start > _EPOCH:
            token = quote(start.isoformat(timespec="seconds"))
            params.append(f"token={token}")
        return f"{base_url}?{'&'.join(params)}"

    def _fetch_one_delta_page(
        self,
        page_url: str,
        drive_id: str,
        start: datetime | None = None,
        end: datetime | None = None,
        page_size: int = 200,
    ) -> tuple[list[DriveItemData], str | None]:
        """Fetch a single page of delta API results.

        Returns ``(items, next_page_url)``.  *next_page_url* is ``None`` when
        the delta enumeration is complete (deltaLink with no nextLink).

        On 410 Gone (expired token) returns ``([], full_resync_url)`` so
        the caller can store the resync URL in the checkpoint and retry on
        the next cycle.
        """
        try:
            data = self._graph_api_get_json(page_url)
        except requests.HTTPError as e:
            if e.response is not None and e.response.status_code == 410:
                logger.warning(
                    "Delta token expired (410 Gone) for drive '%s'. "
                    "Will restart with full delta enumeration.",
                    drive_id,
                )
                full_url = (
                    f"{self.graph_api_base}/drives/{drive_id}/root/delta"
                    f"?$top={page_size}"
                )
                return [], full_url
            raise

        items: list[DriveItemData] = []
        for item in data.get("value", []):
            if "folder" in item or "deleted" in item:
                continue
            if start is not None or end is not None:
                raw_ts = item.get("lastModifiedDateTime")
                if raw_ts:
                    mod_dt = datetime.fromisoformat(raw_ts.replace("Z", "+00:00"))
                    if start is not None and mod_dt < start:
                        continue
                    if end is not None and mod_dt > end:
                        continue
            items.append(DriveItemData.from_graph_json(item))

        next_url = data.get("@odata.nextLink")
        if next_url:
            return items, next_url
        return items, None

    @staticmethod
    def _clear_drive_checkpoint_state(
        checkpoint: "SharepointConnectorCheckpoint",
    ) -> None:
        """Reset all drive-level fields in the checkpoint."""
        checkpoint.current_drive_name = None
        checkpoint.current_drive_id = None
        checkpoint.current_drive_web_url = None
        checkpoint.current_drive_delta_next_link = None

    def _fetch_slim_documents_from_sharepoint(self) -> GenerateSlimDocumentOutput:
        site_descriptors = self.site_descriptors or self.fetch_sites()

        # Create a temporary checkpoint for hierarchy node tracking
        temp_checkpoint = SharepointConnectorCheckpoint(has_more=True)

        # goes over all urls, converts them into SlimDocument objects and then yields them in batches
        doc_batch: list[SlimDocument | HierarchyNode] = []
        for site_descriptor in site_descriptors:
            site_url = site_descriptor.url

            # Yield site hierarchy node using helper
            doc_batch.extend(
                self._yield_site_hierarchy_node(site_descriptor, temp_checkpoint)
            )

            # Process site documents if flag is True
            if self.include_site_documents:
                for driveitem, drive_name, drive_web_url in self._fetch_driveitems(
                    site_descriptor=site_descriptor
                ):
                    if drive_web_url:
                        doc_batch.extend(
                            self._yield_drive_hierarchy_node(
                                site_url, drive_web_url, drive_name, temp_checkpoint
                            )
                        )

                    folder_path = self._extract_folder_path_from_parent_reference(
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
                            )
                        )

                    try:
                        logger.debug(f"Processing: {driveitem.web_url}")
                        ctx = self._create_rest_client_context(site_descriptor.url)
                        doc_batch.append(
                            _convert_driveitem_to_slim_document(
                                driveitem, drive_name, ctx, self.graph_client
                            )
                        )
                    except Exception as e:
                        logger.warning(f"Failed to process driveitem: {str(e)}")

                    if len(doc_batch) >= SLIM_BATCH_SIZE:
                        yield doc_batch
                        doc_batch = []

            # Process site pages if flag is True
            if self.include_site_pages:
                site_pages = self._fetch_site_pages(site_descriptor)
                for site_page in site_pages:
                    logger.debug(
                        f"Processing site page: {site_page.get('webUrl', site_page.get('name', 'Unknown'))}"
                    )
                    ctx = self._create_rest_client_context(site_descriptor.url)
                    doc_batch.append(
                        _convert_sitepage_to_slim_document(
                            site_page, ctx, self.graph_client
                        )
                    )
                    if len(doc_batch) >= SLIM_BATCH_SIZE:
                        yield doc_batch
                        doc_batch = []
        yield doc_batch

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        self._credential_json = credentials
        auth_method = credentials.get(
            "authentication_method", SharepointAuthMethod.CLIENT_SECRET.value
        )
        sp_client_id = credentials.get("sp_client_id")
        sp_client_secret = credentials.get("sp_client_secret")
        sp_directory_id = credentials.get("sp_directory_id")
        sp_private_key = credentials.get("sp_private_key")
        sp_certificate_password = credentials.get("sp_certificate_password")

        authority_url = f"{self.authority_host}/{sp_directory_id}"

        if auth_method == SharepointAuthMethod.CERTIFICATE.value:
            logger.info("Using certificate authentication")
            if not sp_private_key or not sp_certificate_password:
                raise ConnectorValidationError(
                    "Private key and certificate password are required for certificate authentication"
                )

            pfx_data = base64.b64decode(sp_private_key)
            certificate_data = load_certificate_from_pfx(
                pfx_data, sp_certificate_password
            )
            if certificate_data is None:
                raise RuntimeError("Failed to load certificate")

            logger.info(f"Creating MSAL app with authority url {authority_url}")
            self.msal_app = msal.ConfidentialClientApplication(
                authority=authority_url,
                client_id=sp_client_id,
                client_credential=certificate_data.model_dump(),
            )
        elif auth_method == SharepointAuthMethod.CLIENT_SECRET.value:
            logger.info("Using client secret authentication")
            self.msal_app = msal.ConfidentialClientApplication(
                authority=authority_url,
                client_id=sp_client_id,
                client_credential=sp_client_secret,
            )
        else:
            raise ConnectorValidationError(
                "Invalid authentication method or missing required credentials"
            )

        def _acquire_token_for_graph() -> dict[str, Any]:
            """
            Acquire token via MSAL
            """
            if self.msal_app is None:
                raise ConnectorValidationError("MSAL app is not initialized")

            token = self.msal_app.acquire_token_for_client(
                scopes=[f"{self.graph_api_host}/.default"]
            )
            if token is None:
                raise ConnectorValidationError("Failed to acquire token for graph")
            return token

        self._graph_client = GraphClient(
            _acquire_token_for_graph, environment=self._azure_environment
        )
        if auth_method == SharepointAuthMethod.CERTIFICATE.value:
            org = self.graph_client.organization.get().execute_query()
            if not org or len(org) == 0:
                raise ConnectorValidationError("No organization found")

            tenant_info: Organization = org[
                0
            ]  # Access first item directly from collection
            if not tenant_info.verified_domains:
                raise ConnectorValidationError("No verified domains found for tenant")

            sp_tenant_domain = tenant_info.verified_domains[0].name
            if not sp_tenant_domain:
                raise ConnectorValidationError("No verified domains found for tenant")
            # remove the .onmicrosoft.com part
            self.sp_tenant_domain = sp_tenant_domain.split(".")[0]
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
            logger.warning(f"Failed to fetch drives for site '{site_url}': {e}")
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

    def _extract_folder_path_from_parent_reference(
        self, parent_reference_path: str | None
    ) -> str | None:
        """Extract folder path from DriveItem's parentReference.path.

        Example input: "/drives/b!abc123/root:/Engineering/API"
        Example output: "Engineering/API"

        Returns None if the item is at the root of the drive.
        """
        if not parent_reference_path:
            return None

        # Path format: /drives/{drive_id}/root:/folder/path
        if "root:/" in parent_reference_path:
            folder_path = parent_reference_path.split("root:/")[1]
            return folder_path if folder_path else None

        # Item is at drive root
        return None

    def _yield_site_hierarchy_node(
        self,
        site_descriptor: SiteDescriptor,
        checkpoint: SharepointConnectorCheckpoint,
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

        yield HierarchyNode(
            raw_node_id=site_url,
            raw_parent_id=None,  # Parent is SOURCE
            display_name=display_name,
            link=site_url,
            node_type=HierarchyNodeType.SITE,
        )

    def _yield_drive_hierarchy_node(
        self,
        site_url: str,
        drive_web_url: str,
        drive_name: str,
        checkpoint: SharepointConnectorCheckpoint,
    ) -> Generator[HierarchyNode, None, None]:
        """Yield a hierarchy node for a drive if not already yielded.

        Uses drive.web_url as the raw_node_id (exact URL from API).
        """
        if drive_web_url in checkpoint.seen_hierarchy_node_raw_ids:
            return

        checkpoint.seen_hierarchy_node_raw_ids.add(drive_web_url)

        yield HierarchyNode(
            raw_node_id=drive_web_url,
            raw_parent_id=site_url,  # Site URL is parent
            display_name=drive_name,
            link=drive_web_url,
            node_type=HierarchyNodeType.DRIVE,
        )

    def _yield_folder_hierarchy_nodes(
        self,
        site_url: str,
        drive_web_url: str,
        drive_name: str,
        folder_path: str,
        checkpoint: SharepointConnectorCheckpoint,
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
        folder_path = self._extract_folder_path_from_parent_reference(
            driveitem.parent_reference_path
        )

        if folder_path:
            return self._build_folder_url(site_url, drive_name, folder_path)

        # Document is at drive root
        return drive_web_url

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
            site_descs = self.site_descriptors or self.fetch_sites()
            checkpoint.cached_site_descriptors = deque(site_descs)

            if not checkpoint.cached_site_descriptors:
                logger.warning(
                    "No SharePoint sites found or accessible - nothing to process"
                )
                checkpoint.has_more = False
                return checkpoint

            logger.info(
                f"Found {len(checkpoint.cached_site_descriptors)} sites to process"
            )
            # Set first site and return to allow checkpoint persistence
            if checkpoint.cached_site_descriptors:
                checkpoint.current_site_descriptor = (
                    checkpoint.cached_site_descriptors.popleft()
                )
                logger.info(
                    f"Starting with site: {checkpoint.current_site_descriptor.url}"
                )
                # Yield site hierarchy node for the first site
                yield from self._yield_site_hierarchy_node(
                    checkpoint.current_site_descriptor, checkpoint
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
                f"Initializing drives for site: {checkpoint.current_site_descriptor.url}"
            )

            try:
                # If the user explicitly specified drive(s) for this site, honour that
                if checkpoint.current_site_descriptor.drive_name:
                    logger.info(
                        f"Using explicitly specified drive: {checkpoint.current_site_descriptor.drive_name}"
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
                        f"No accessible drives found for site: {checkpoint.current_site_descriptor.url}"
                    )
                else:
                    logger.info(
                        f"Found {len(checkpoint.cached_drive_names)} drives: {list(checkpoint.cached_drive_names)}"
                    )

            except Exception as e:
                logger.error(
                    f"Failed to initialize drives for site: {checkpoint.current_site_descriptor.url}: {e}"
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
                f"Processing drive '{checkpoint.current_drive_name}' "
                f"in site: {site_descriptor.url}"
            )
            logger.debug(f"Time range: {start_dt} to {end_dt}")

            current_drive_name = checkpoint.current_drive_name
            if current_drive_name is None:
                logger.warning("Current drive name is None, skipping")
                return checkpoint

            try:
                logger.info(
                    f"Fetching drive items for drive name: {current_drive_name}"
                )
                result = self._resolve_drive(site_descriptor, current_drive_name)
                if result is None:
                    logger.warning(f"Drive '{current_drive_name}' not found, skipping")
                    self._clear_drive_checkpoint_state(checkpoint)
                    return checkpoint

                drive_id, drive_web_url = result
                checkpoint.current_drive_id = drive_id
                checkpoint.current_drive_web_url = drive_web_url
            except Exception as e:
                logger.error(
                    f"Failed to retrieve items from drive '{current_drive_name}' "
                    f"in site: {site_descriptor.url}: {e}"
                )
                yield _create_entity_failure(
                    f"{site_descriptor.url}|{current_drive_name}",
                    f"Failed to access drive '{current_drive_name}' "
                    f"in site '{site_descriptor.url}': {str(e)}",
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
                )

            # For non-folder-scoped drives, use delta API with per-page
            # checkpointing.  Build the initial URL and fall through to 3b.
            if not site_descriptor.folder_path:
                checkpoint.current_drive_delta_next_link = self._build_delta_start_url(
                    drive_id, start_dt
                )
            # else: BFS path — delta_next_link stays None;
            # Phase 3b will use _iter_drive_items_paged.

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
                    page_items, next_url = self._fetch_one_delta_page(
                        page_url=checkpoint.current_drive_delta_next_link,
                        drive_id=checkpoint.current_drive_id,
                        start=start_dt,
                        end=end_dt,
                    )
                except Exception as e:
                    logger.error(
                        f"Failed to fetch delta page for drive "
                        f"'{current_drive_name}': {e}"
                    )
                    yield _create_entity_failure(
                        f"{site_descriptor.url}|{current_drive_name}",
                        f"Failed to fetch delta page for drive "
                        f"'{current_drive_name}': {str(e)}",
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
                driveitems = self._iter_drive_items_paged(
                    drive_id=checkpoint.current_drive_id,
                    folder_path=site_descriptor.folder_path,
                    start=start_dt,
                    end=end_dt,
                )

            item_count = 0
            for driveitem in driveitems:
                item_count += 1
                driveitem_extension = get_file_ext(driveitem.name)
                if driveitem_extension not in OnyxFileExtensions.ALL_ALLOWED_EXTENSIONS:
                    logger.warning(
                        f"Skipping {driveitem.web_url} as it is not a supported file type"
                    )
                    continue

                should_yield_if_empty = (
                    driveitem_extension in OnyxFileExtensions.IMAGE_EXTENSIONS
                    or driveitem_extension == ".pdf"
                )

                folder_path = self._extract_folder_path_from_parent_reference(
                    driveitem.parent_reference_path
                )
                if folder_path and drive_web_url:
                    yield from self._yield_folder_hierarchy_nodes(
                        site_descriptor.url,
                        drive_web_url,
                        current_drive_name,
                        folder_path,
                        checkpoint,
                    )

                parent_hierarchy_url: str | None = None
                if drive_web_url:
                    parent_hierarchy_url = self._get_parent_hierarchy_url(
                        site_descriptor.url,
                        drive_web_url,
                        current_drive_name,
                        driveitem,
                    )

                try:
                    ctx: ClientContext | None = None
                    if include_permissions:
                        ctx = self._create_rest_client_context(site_descriptor.url)

                    access_token = self._get_graph_access_token()
                    doc_or_failure = _convert_driveitem_to_document_with_permissions(
                        driveitem,
                        current_drive_name,
                        ctx,
                        self.graph_client,
                        include_permissions=include_permissions,
                        parent_hierarchy_raw_node_id=parent_hierarchy_url,
                        graph_api_base=self.graph_api_base,
                        access_token=access_token,
                    )

                    if isinstance(doc_or_failure, Document):
                        if doc_or_failure.sections:
                            yield doc_or_failure
                        elif should_yield_if_empty:
                            doc_or_failure.sections = [
                                TextSection(link=driveitem.web_url, text="")
                            ]
                            yield doc_or_failure
                        else:
                            logger.warning(
                                f"Skipping {driveitem.web_url} as it is empty and not a PDF or image"
                            )
                    elif isinstance(doc_or_failure, ConnectorFailure):
                        yield doc_or_failure
                except Exception as e:
                    logger.warning(
                        f"Failed to process driveitem {driveitem.web_url}: {e}"
                    )
                    yield _create_document_failure(
                        driveitem, f"Failed to process: {str(e)}", e
                    )

            logger.info(f"Processed {item_count} items in drive '{current_drive_name}'")

            if has_more_delta_pages:
                return checkpoint

            self._clear_drive_checkpoint_state(checkpoint)

        # Phase 4: Progression logic - determine next step
        # If we have more drives in current site, continue with current site
        if checkpoint.cached_drive_names and len(checkpoint.cached_drive_names) > 0:
            logger.debug(
                f"Continuing with {len(checkpoint.cached_drive_names)} remaining drives in current site"
            )
            return checkpoint

        if (
            self.include_site_pages
            and not checkpoint.process_site_pages
            and checkpoint.current_site_descriptor is not None
        ):
            logger.info(
                f"Processing site pages for site: {checkpoint.current_site_descriptor.url}"
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
            site_pages = self._fetch_site_pages(
                site_descriptor, start=start_dt, end=end_dt
            )
            for site_page in site_pages:
                logger.debug(
                    f"Processing site page: {site_page.get('webUrl', site_page.get('name', 'Unknown'))}"
                )
                client_ctx: ClientContext | None = None
                if include_permissions:
                    client_ctx = self._create_rest_client_context(site_descriptor.url)
                yield (
                    _convert_sitepage_to_document(
                        site_page,
                        site_descriptor.drive_name,
                        client_ctx,
                        self.graph_client,
                        include_permissions=include_permissions,
                        # Site pages have the site as their parent
                        parent_hierarchy_raw_node_id=site_descriptor.url,
                    )
                )
            logger.info(
                f"Finished processing site pages for site: {site_descriptor.url}"
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
                f"Finished site '{current_site}', moving to next site: {checkpoint.current_site_descriptor.url}"
            )
            logger.info(
                f"Remaining sites to process: {len(checkpoint.cached_site_descriptors) + 1}"
            )
            # Yield site hierarchy node for the new site
            yield from self._yield_site_hierarchy_node(
                checkpoint.current_site_descriptor, checkpoint
            )
            return checkpoint

        # No more sites or drives - we're done
        current_site = (
            checkpoint.current_site_descriptor.url
            if checkpoint.current_site_descriptor
            else "unknown"
        )
        logger.info(
            f"SharePoint processing complete. Finished last site: {current_site}"
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

    def build_dummy_checkpoint(self) -> SharepointConnectorCheckpoint:
        return SharepointConnectorCheckpoint(has_more=True)

    def validate_checkpoint_json(
        self, checkpoint_json: str
    ) -> SharepointConnectorCheckpoint:
        return SharepointConnectorCheckpoint.model_validate_json(checkpoint_json)

    def retrieve_all_slim_docs_perm_sync(
        self,
        start: SecondsSinceUnixEpoch | None = None,  # noqa: ARG002
        end: SecondsSinceUnixEpoch | None = None,  # noqa: ARG002
        callback: IndexingHeartbeatInterface | None = None,  # noqa: ARG002
    ) -> GenerateSlimDocumentOutput:

        yield from self._fetch_slim_documents_from_sharepoint()


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
        for doc_batch, hierarchy_node_batch, failure, next_checkpoint in runner.run(
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
