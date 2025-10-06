import base64
import copy
import html
import io
import os
import re
import time
from collections import deque
from collections.abc import Generator
from datetime import datetime
from datetime import timezone
from enum import Enum
from typing import Any
from typing import cast
from urllib.parse import unquote

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
from office365.runtime.queries.client_query import ClientQuery  # type: ignore[import-untyped]
from office365.sharepoint.client_context import ClientContext  # type: ignore[import-untyped]
from pydantic import BaseModel

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
from onyx.connectors.models import BasicExpertInfo
from onyx.connectors.models import ConnectorCheckpoint
from onyx.connectors.models import ConnectorFailure
from onyx.connectors.models import ConnectorMissingCredentialError
from onyx.connectors.models import Document
from onyx.connectors.models import DocumentFailure
from onyx.connectors.models import EntityFailure
from onyx.connectors.models import ExternalAccess
from onyx.connectors.models import ImageSection
from onyx.connectors.models import SlimDocument
from onyx.connectors.models import TextSection
from onyx.connectors.sharepoint.connector_utils import get_sharepoint_external_access
from onyx.file_processing.extract_file_text import ACCEPTED_IMAGE_FILE_EXTENSIONS
from onyx.file_processing.extract_file_text import extract_text_and_images
from onyx.file_processing.extract_file_text import get_file_ext
from onyx.file_processing.file_validation import EXCLUDED_IMAGE_TYPES
from onyx.file_processing.image_utils import store_image_and_create_section
from onyx.utils.b64 import get_image_type_from_bytes
from onyx.utils.logger import setup_logger

logger = setup_logger()
SLIM_BATCH_SIZE = 1000


ASPX_EXTENSION = ".aspx"


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
            if (
                e.response is not None
                and e.response.status_code in [429, 503]
                and attempt < max_retries
            ):
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
            else:
                # Either not a rate limit error, or we've exhausted retries
                if e.response is not None and e.response.status_code == 429:
                    logger.error(
                        f"Rate limit retry exhausted for {method_name} after {max_retries} attempts"
                    )
                raise e


class SharepointConnectorCheckpoint(ConnectorCheckpoint):
    cached_site_descriptors: deque[SiteDescriptor] | None = None
    current_site_descriptor: SiteDescriptor | None = None

    cached_drive_names: deque[str] | None = None
    current_drive_name: str | None = None

    process_site_pages: bool = False


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
    msal_app: msal.ConfidentialClientApplication, sp_tenant_domain: str
) -> TokenResponse:
    token = msal_app.acquire_token_for_client(
        scopes=[f"https://{sp_tenant_domain}.sharepoint.com/.default"]
    )
    return TokenResponse.from_json(token)


def _get_download_url(driveitem: DriveItem) -> str | None:
    """Best-effort retrieval of the Microsoft Graph download URL from a DriveItem."""
    try:
        additional_data = getattr(driveitem, "additional_data", None)
        if isinstance(additional_data, dict):
            url = additional_data.get("@microsoft.graph.downloadUrl")
            if isinstance(url, str) and url:
                return url
    except Exception:
        pass

    try:
        driveitem_json = driveitem.to_json()
        url = driveitem_json.get("@microsoft.graph.downloadUrl")
        if isinstance(url, str) and url:
            return url
    except Exception:
        pass
    return None


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


def _download_via_sdk_with_cap(
    driveitem: DriveItem, bytes_allowed: int, chunk_size: int = 64 * 1024
) -> bytes:
    """Use the Office365 SDK streaming download with a hard byte cap.

    Raises SizeCapExceeded("during_sdk_download") if the cap would be exceeded.
    """
    buf = io.BytesIO()

    def on_chunk(bytes_read: int) -> None:
        # bytes_read is total bytes seen so far per SDK contract
        if bytes_read > bytes_allowed:
            raise SizeCapExceeded("during_sdk_download")

    # modifies the driveitem to change its download behavior
    driveitem.download_session(buf, chunk_downloaded=on_chunk, chunk_size=chunk_size)
    # Execute the configured request with retries using existing helper
    sleep_and_retry(driveitem.context, "download_session")
    return buf.getvalue()


def _convert_driveitem_to_document_with_permissions(
    driveitem: DriveItem,
    drive_name: str,
    ctx: ClientContext | None,
    graph_client: GraphClient,
    include_permissions: bool = False,
) -> Document | None:

    if not driveitem.name or not driveitem.id:
        raise ValueError("DriveItem name/id is required")

    if include_permissions and ctx is None:
        raise ValueError("ClientContext is required for permissions")

    # Determine size before downloading, when possible
    file_size: int | None = None
    try:
        item_json = driveitem.to_json()
        mime_type = item_json.get("file", {}).get("mimeType")
        if not mime_type or mime_type in EXCLUDED_IMAGE_TYPES:
            # NOTE: this function should be refactored to look like Drive doc_conversion.py pattern
            # for now, this skip must happen before we download the file
            # Similar to Google Drive, we'll just semi-silently skip excluded image types
            logger.debug(
                f"Skipping malformed or excluded mime type {mime_type} for {driveitem.name}"
            )
            return None

        size_value = item_json.get("size")
        if size_value is not None:
            file_size = int(size_value)
    except Exception as e:
        logger.debug(
            f"Could not access file size for '{driveitem.name}' from item JSON: {e}"
        )

    download_url = _get_download_url(driveitem)
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
            # Use this to test the sdk size cap
            # raise requests.RequestException("test")
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
                f"Failed to download via downloadUrl for '{driveitem.name}' (status={status}); falling back to SDK."
            )

    # Fallback to SDK content if needed
    if content_bytes is None:
        try:
            content_bytes = _download_via_sdk_with_cap(
                driveitem, SHAREPOINT_CONNECTOR_SIZE_THRESHOLD
            )
        except SizeCapExceeded:
            logger.warning(
                f"Skipping '{driveitem.name}' exceeded size cap during SDK streaming."
            )
            return None

    sections: list[TextSection | ImageSection] = []
    file_ext = driveitem.name.split(".")[-1]

    if not content_bytes:
        logger.warning(
            f"Zero-length content for '{driveitem.name}'. Skipping text/image extraction."
        )
    elif "." + file_ext in ACCEPTED_IMAGE_FILE_EXTENSIONS:
        # NOTE: this if should use is_valid_image_type instead with mime_type
        image_section, _ = store_image_and_create_section(
            image_data=content_bytes,
            file_id=driveitem.id,
            display_name=driveitem.name,
            file_origin=FileOrigin.CONNECTOR,
        )
        image_section.link = driveitem.web_url
        sections.append(image_section)
    else:
        # Note: we don't process Onyx metadata for connectors like Drive & Sharepoint, but could
        def _store_embedded_image(img_data: bytes, img_name: str) -> None:
            try:
                mime_type = get_image_type_from_bytes(img_data)
            except ValueError:
                logger.debug(
                    "Skipping embedded image with unknown format for %s",
                    driveitem.name,
                )
                return

            # The only mime type that would be returned by get_image_type_from_bytes that is in
            # EXCLUDED_IMAGE_TYPES is image/gif.
            if mime_type in EXCLUDED_IMAGE_TYPES:
                logger.debug(
                    "Skipping embedded image of excluded type %s for %s",
                    mime_type,
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
        # Any embedded images were stored via the callback; the returned list may be empty.

    if include_permissions and ctx is not None:
        logger.info(f"Getting external access for {driveitem.name}")
        external_access = get_sharepoint_external_access(
            ctx=ctx,
            graph_client=graph_client,
            drive_item=driveitem,
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
                display_name=driveitem.last_modified_by.user.displayName,
                email=getattr(driveitem.last_modified_by.user, "email", "")
                or getattr(driveitem.last_modified_by.user, "userPrincipalName", ""),
            )
        ],
        metadata={"drive": drive_name},
    )
    return doc


def _convert_sitepage_to_document(
    site_page: dict[str, Any],
    site_name: str | None,
    ctx: ClientContext | None,
    graph_client: GraphClient,
    include_permissions: bool = False,
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
    )
    return doc


def _convert_driveitem_to_slim_document(
    driveitem: DriveItem,
    drive_name: str,
    ctx: ClientContext,
    graph_client: GraphClient,
) -> SlimDocument:
    if driveitem.id is None:
        raise ValueError("DriveItem ID is required")

    external_access = get_sharepoint_external_access(
        ctx=ctx,
        graph_client=graph_client,
        drive_item=driveitem,
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

    @staticmethod
    def _extract_site_and_drive_info(site_urls: list[str]) -> list[SiteDescriptor]:
        site_data_list = []
        for url in site_urls:
            parts = url.strip().split("/")

            site_type_index = None
            if "sites" in parts:
                site_type_index = parts.index("sites")
            elif "teams" in parts:
                site_type_index = parts.index("teams")

            if site_type_index is not None:
                # Extract the base site URL (up to and including the site/team name)
                site_url = "/".join(parts[: site_type_index + 2])
                remaining_parts = parts[site_type_index + 2 :]

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
            else:
                logger.warning(
                    f"Site URL '{url}' is not a valid Sharepoint URL (must contain /sites/ or /teams/)"
                )
        return site_data_list

    def _get_drive_items_for_drive_name(
        self,
        site_descriptor: SiteDescriptor,
        drive_name: str,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list[DriveItem]:
        try:
            site = self.graph_client.sites.get_by_url(site_descriptor.url)
            drives = site.drives.get().execute_query()
            logger.debug(f"Found drives: {[drive.name for drive in drives]}")

            drives = [
                drive
                for drive in drives
                if (drive.name and drive.name.lower() == drive_name.lower())
                or (drive.name == "Documents" and drive_name == "Shared Documents")
            ]
            drive = drives[0] if len(drives) > 0 else None
            if drive is None:
                logger.warning(f"Drive '{drive_name}' not found")
                return []
            try:
                root_folder = drive.root
                if site_descriptor.folder_path:
                    for folder_part in site_descriptor.folder_path.split("/"):
                        root_folder = root_folder.get_by_path(folder_part)

                # TODO: consider ways to avoid materializing the entire list of files in memory
                query = root_folder.get_files(
                    recursive=True,
                    page_size=1000,
                )
                driveitems = query.execute_query()
                logger.debug(f"Found {len(driveitems)} items in drive '{drive_name}'")

                # Filter items based on folder path if specified
                if site_descriptor.folder_path:
                    # Filter items to ensure they're in the specified folder or its subfolders
                    # The path will be in format: /drives/{drive_id}/root:/folder/path
                    driveitems = [
                        item
                        for item in driveitems
                        if item.parent_reference.path
                        and "root:/" in item.parent_reference.path
                        and (
                            item.parent_reference.path.split("root:/")[1]
                            == site_descriptor.folder_path
                            or item.parent_reference.path.split("root:/")[1].startswith(
                                site_descriptor.folder_path + "/"
                            )
                        )
                    ]
                    if len(driveitems) == 0:
                        all_paths = [item.parent_reference.path for item in driveitems]
                        logger.warning(
                            f"Nothing found for folder '{site_descriptor.folder_path}' "
                            f"in; any of valid paths: {all_paths}"
                        )
                    logger.info(
                        f"Found {len(driveitems)} items in drive '{drive_name}' for the folder '{site_descriptor.folder_path}'"
                    )

                # Filter items based on time window if specified
                if start is not None and end is not None:
                    driveitems = [
                        item
                        for item in driveitems
                        if item.last_modified_datetime
                        and start
                        <= item.last_modified_datetime.replace(tzinfo=timezone.utc)
                        <= end
                    ]
                    logger.debug(
                        f"Found {len(driveitems)} items within time window in drive '{drive.name}'"
                    )

                return list(driveitems)

            except Exception as e:
                # Some drives might not be accessible
                logger.warning(f"Failed to process drive: {str(e)}")
                return []

        except Exception as e:
            err_str = str(e)
            if (
                "403 Client Error" in err_str
                or "404 Client Error" in err_str
                or "invalid_client" in err_str
            ):
                raise e

            # Sites include things that do not contain drives so this fails
            # but this is fine, as there are no actual documents in those
            logger.warning(f"Failed to process site: {site_descriptor.url} - {err_str}")
            return []

    def _fetch_driveitems(
        self,
        site_descriptor: SiteDescriptor,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list[tuple[DriveItem, str]]:
        final_driveitems: list[tuple[DriveItem, str]] = []
        try:
            site = self.graph_client.sites.get_by_url(site_descriptor.url)

            # Get all drives in the site
            drives = site.drives.get().execute_query()
            logger.debug(f"Found drives: {[drive.name for drive in drives]}")

            # Filter drives based on the requested drive name
            if site_descriptor.drive_name:
                drives = [
                    drive
                    for drive in drives
                    if drive.name == site_descriptor.drive_name
                    or (
                        drive.name == "Documents"
                        and site_descriptor.drive_name == "Shared Documents"
                    )
                ]
                if not drives:
                    logger.warning(f"Drive '{site_descriptor.drive_name}' not found")
                    return []

            # Process each matching drive
            for drive in drives:
                try:
                    root_folder = drive.root
                    if site_descriptor.folder_path:
                        # If a specific folder is requested, navigate to it
                        for folder_part in site_descriptor.folder_path.split("/"):
                            root_folder = root_folder.get_by_path(folder_part)

                    # Get all items recursively
                    # TODO: consider ways to avoid materializing the entire list of files in memory
                    query = root_folder.get_files(
                        recursive=True,
                        page_size=1000,
                    )
                    driveitems = query.execute_query()
                    logger.debug(
                        f"Found {len(driveitems)} items in drive '{drive.name}'"
                    )

                    # Use "Shared Documents" as the library name for the default "Documents" drive
                    drive_name = (
                        "Shared Documents"
                        if drive.name == "Documents"
                        else cast(str, drive.name)
                    )

                    # Filter items based on folder path if specified
                    if site_descriptor.folder_path:
                        # Filter items to ensure they're in the specified folder or its subfolders
                        # The path will be in format: /drives/{drive_id}/root:/folder/path
                        driveitems = [
                            item
                            for item in driveitems
                            if item.parent_reference.path
                            and "root:/" in item.parent_reference.path
                            and (
                                item.parent_reference.path.split("root:/")[1]
                                == site_descriptor.folder_path
                                or item.parent_reference.path.split("root:/")[
                                    1
                                ].startswith(site_descriptor.folder_path + "/")
                            )
                        ]
                        if len(driveitems) == 0:
                            all_paths = [
                                item.parent_reference.path for item in driveitems
                            ]
                            logger.warning(
                                f"Nothing found for folder '{site_descriptor.folder_path}' "
                                f"in; any of valid paths: {all_paths}"
                            )

                    # Filter items based on time window if specified
                    if start is not None and end is not None:
                        driveitems = [
                            item
                            for item in driveitems
                            if item.last_modified_datetime
                            and start
                            <= item.last_modified_datetime.replace(tzinfo=timezone.utc)
                            <= end
                        ]
                        logger.debug(
                            f"Found {len(driveitems)} items within time window in drive '{drive.name}'"
                        )

                    for item in driveitems:
                        final_driveitems.append((item, drive_name or ""))

                except Exception as e:
                    # Some drives might not be accessible
                    logger.warning(f"Failed to process drive '{drive.name}': {str(e)}")

        except Exception as e:
            err_str = str(e)
            if (
                "403 Client Error" in err_str
                or "404 Client Error" in err_str
                or "invalid_client" in err_str
            ):
                raise e

            # Sites include things that do not contain drives so this fails
            # but this is fine, as there are no actual documents in those
            logger.warning(f"Failed to process site: {err_str}")

        return final_driveitems

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
    ) -> list[dict[str, Any]]:
        """Fetch SharePoint site pages (.aspx files) using the SharePoint Pages API."""

        # Get the site to extract the site ID
        site = self.graph_client.sites.get_by_url(site_descriptor.url)
        site.execute_query()  # Execute the query to actually fetch the data
        site_id = site.id

        # Get the token acquisition function from the GraphClient
        token_data = self._acquire_token()
        access_token = token_data.get("access_token")
        if not access_token:
            raise RuntimeError("Failed to acquire access token")

        # Construct the SharePoint Pages API endpoint
        # Using API directly, since the Graph Client doesn't support the Pages API
        pages_endpoint = f"https://graph.microsoft.com/v1.0/sites/{site_id}/pages/microsoft.graph.sitePage"

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }

        # Add expand parameter to get canvas layout content
        params = {"$expand": "canvasLayout"}

        response = requests.get(
            pages_endpoint,
            headers=headers,
            params=params,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        pages_data = response.json()
        all_pages = pages_data.get("value", [])

        # Handle pagination if there are more pages
        # TODO: This accumulates all pages in memory and can be heavy on large tenants.
        #       We should process each page incrementally to avoid unbounded growth.
        while "@odata.nextLink" in pages_data:
            next_url = pages_data["@odata.nextLink"]
            response = requests.get(
                next_url, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS
            )
            response.raise_for_status()
            pages_data = response.json()
            all_pages.extend(pages_data.get("value", []))

        logger.debug(f"Found {len(all_pages)} site pages in {site_descriptor.url}")

        # Filter pages based on time window if specified
        if start is not None or end is not None:
            filtered_pages: list[dict[str, Any]] = []
            for page in all_pages:
                page_modified = page.get("lastModifiedDateTime")
                if page_modified:
                    if isinstance(page_modified, str):
                        page_modified = datetime.fromisoformat(
                            page_modified.replace("Z", "+00:00")
                        )

                    if start is not None and page_modified < start:
                        continue
                    if end is not None and page_modified > end:
                        continue

                filtered_pages.append(page)
            all_pages = filtered_pages

        return all_pages

    def _acquire_token(self) -> dict[str, Any]:
        """
        Acquire token via MSAL
        """
        if self.msal_app is None:
            raise RuntimeError("MSAL app is not initialized")

        token = self.msal_app.acquire_token_for_client(
            scopes=["https://graph.microsoft.com/.default"]
        )
        return token

    def _fetch_slim_documents_from_sharepoint(self) -> GenerateSlimDocumentOutput:
        site_descriptors = self.site_descriptors or self.fetch_sites()

        # goes over all urls, converts them into SlimDocument objects and then yields them in batches
        doc_batch: list[SlimDocument] = []
        for site_descriptor in site_descriptors:
            ctx: ClientContext | None = None

            if self.msal_app and self.sp_tenant_domain:
                msal_app = self.msal_app
                sp_tenant_domain = self.sp_tenant_domain
                ctx = ClientContext(site_descriptor.url).with_access_token(
                    lambda: acquire_token_for_rest(msal_app, sp_tenant_domain)
                )
            else:
                raise RuntimeError("MSAL app or tenant domain is not set")

            if ctx is None:
                logger.warning("ClientContext is not set, skipping permissions")
                continue

            # Process site documents if flag is True
            if self.include_site_documents:
                driveitems = self._fetch_driveitems(site_descriptor=site_descriptor)
                for driveitem, drive_name in driveitems:
                    try:
                        logger.debug(f"Processing: {driveitem.web_url}")
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
        auth_method = credentials.get(
            "authentication_method", SharepointAuthMethod.CLIENT_SECRET.value
        )
        sp_client_id = credentials.get("sp_client_id")
        sp_client_secret = credentials.get("sp_client_secret")
        sp_directory_id = credentials.get("sp_directory_id")
        sp_private_key = credentials.get("sp_private_key")
        sp_certificate_password = credentials.get("sp_certificate_password")

        authority_url = f"https://login.microsoftonline.com/{sp_directory_id}"

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
                scopes=["https://graph.microsoft.com/.default"]
            )
            if token is None:
                raise ConnectorValidationError("Failed to acquire token for graph")
            return token

        self._graph_client = GraphClient(_acquire_token_for_graph)
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

    def _create_document_failure(
        self,
        driveitem: DriveItem,
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
        self,
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
                yield self._create_entity_failure(
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

        # Phase 3: Process documents from current drive
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
                f"Processing drive '{checkpoint.current_drive_name}' in site: {site_descriptor.url}"
            )
            logger.debug(f"Time range: {start_dt} to {end_dt}")

            ctx: ClientContext | None = None
            if include_permissions:
                if self.msal_app and self.sp_tenant_domain:
                    msal_app = self.msal_app
                    sp_tenant_domain = self.sp_tenant_domain
                    ctx = ClientContext(site_descriptor.url).with_access_token(
                        lambda: acquire_token_for_rest(msal_app, sp_tenant_domain)
                    )
                else:
                    raise RuntimeError("MSAL app or tenant domain is not set")

            # At this point current_drive_name should be set from popleft()
            current_drive_name = checkpoint.current_drive_name
            if current_drive_name is None:
                logger.warning("Current drive name is None, skipping")
                return checkpoint

            try:
                driveitems = self._get_drive_items_for_drive_name(
                    site_descriptor, current_drive_name, start_dt, end_dt
                )

                if not driveitems:
                    logger.warning(
                        f"No drive items found in drive '{current_drive_name}' for site: {site_descriptor.url}"
                    )
                else:
                    logger.info(
                        f"Found {len(driveitems)} items to process in drive '{current_drive_name}'"
                    )
            except Exception as e:
                logger.error(
                    f"Failed to retrieve items from drive '{current_drive_name}' in site: {site_descriptor.url}: {e}"
                )
                # Yield a ConnectorFailure for drive-level access failures
                yield self._create_entity_failure(
                    f"{site_descriptor.url}|{current_drive_name}",
                    f"Failed to access drive '{current_drive_name}' in site '{site_descriptor.url}': {str(e)}",
                    (start_dt, end_dt),
                    e,
                )
                # Clear current drive and continue to next
                checkpoint.current_drive_name = None
                return checkpoint
            current_drive_name = (
                "Shared Documents"
                if current_drive_name == "Documents"
                else current_drive_name
            )
            for driveitem in driveitems:
                driveitem_extension = get_file_ext(driveitem.name)
                # Only yield empty documents if they are PDFs or images
                should_yield_if_empty = (
                    driveitem_extension in ACCEPTED_IMAGE_FILE_EXTENSIONS
                    or driveitem_extension == ".pdf"
                )

                try:
                    doc = _convert_driveitem_to_document_with_permissions(
                        driveitem,
                        current_drive_name,
                        ctx,
                        self.graph_client,
                        include_permissions=include_permissions,
                    )

                    if doc:
                        if doc.sections:
                            yield doc
                        elif should_yield_if_empty:
                            doc.sections = [
                                TextSection(link=driveitem.web_url, text="")
                            ]
                            yield doc
                except Exception as e:
                    logger.warning(
                        f"Failed to process driveitem {driveitem.web_url}: {e}"
                    )
                    # Yield a ConnectorFailure for individual document processing failures
                    yield self._create_document_failure(
                        driveitem, f"Failed to process: {str(e)}", e
                    )

            # Clear current drive after processing
            checkpoint.current_drive_name = None

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
            client_ctx: ClientContext | None = None
            if include_permissions:
                if self.msal_app and self.sp_tenant_domain:
                    msal_app = self.msal_app
                    sp_tenant_domain = self.sp_tenant_domain
                    client_ctx = ClientContext(site_descriptor.url).with_access_token(
                        lambda: acquire_token_for_rest(msal_app, sp_tenant_domain)
                    )
                else:
                    raise RuntimeError("MSAL app or tenant domain is not set")
            for site_page in site_pages:
                logger.debug(
                    f"Processing site page: {site_page.get('webUrl', site_page.get('name', 'Unknown'))}"
                )
                yield (
                    _convert_sitepage_to_document(
                        site_page,
                        site_descriptor.drive_name,
                        client_ctx,
                        self.graph_client,
                        include_permissions=include_permissions,
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
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,
        callback: IndexingHeartbeatInterface | None = None,
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
        for doc_batch, failure, next_checkpoint in runner.run(checkpoint):
            if doc_batch:
                print(f"Retrieved batch of {len(doc_batch)} documents")
                for doc in doc_batch:
                    print(f"Document: {doc.semantic_identifier}")
            if failure:
                print(f"Failure: {failure.failure_message}")
            if next_checkpoint:
                checkpoint = next_checkpoint
