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
from onyx.configs.app_configs import SHAREPOINT_CONNECTOR_SIZE_THRESHOLD
from onyx.configs.constants import DocumentSource
from onyx.configs.constants import FileOrigin
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.interfaces import CheckpointedConnectorWithPermSync
from onyx.connectors.interfaces import CheckpointOutput
from onyx.connectors.interfaces import GenerateSlimDocumentOutput
from onyx.connectors.interfaces import IndexingHeartbeatInterface
from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.interfaces import SlimConnector
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
from onyx.file_processing.extract_file_text import extract_file_text
from onyx.file_processing.image_utils import store_image_and_create_section
from onyx.utils.logger import setup_logger

logger = setup_logger()
SLIM_BATCH_SIZE = 1000


ASPX_EXTENSION = ".aspx"
REQUEST_TIMEOUT = 10


class SiteDescriptor(BaseModel):
    """Data class for storing SharePoint site information.

    Args:
        url: The base site URL (e.g. https://danswerai.sharepoint.com/sites/sharepoint-tests)
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
                e.response
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
                if e.response and e.response.status_code == 429:
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


def _convert_driveitem_to_document_with_permissions(
    driveitem: DriveItem,
    drive_name: str,
    ctx: ClientContext | None,
    graph_client: GraphClient,
    include_permissions: bool = False,
) -> Document:

    if driveitem.name is None:
        raise ValueError("DriveItem name is required")
    if driveitem.id is None:
        raise ValueError("DriveItem ID is required")

    try:
        # Access size from the JSON representation since it's not exposed as a direct attribute
        driveitem_json = driveitem.to_json()
        size_value = driveitem_json.get("size")
        if size_value is not None:
            file_size = int(size_value)
            if file_size > SHAREPOINT_CONNECTOR_SIZE_THRESHOLD:
                logger.warning(
                    f"File '{driveitem.name}' exceeds size threshold of {SHAREPOINT_CONNECTOR_SIZE_THRESHOLD} bytes. "
                    f"File size: {file_size} bytes. Skipping."
                )
                raise ValueError(
                    f"File '{driveitem.name}' exceeds size threshold of {SHAREPOINT_CONNECTOR_SIZE_THRESHOLD} bytes. "
                    f"File size: {file_size} bytes."
                )
        else:
            logger.warning(
                f"Could not access file size for '{driveitem.name}' Proceeding with download."
            )
    except (ValueError, TypeError, AttributeError, KeyError) as e:
        logger.info(
            f"Could not access file size for '{driveitem.name}': {e}. Proceeding with download."
        )
    if include_permissions and ctx is None:
        raise ValueError("ClientContext is required for permissions")

    # Proceed with download if size is acceptable or not available
    content = sleep_and_retry(driveitem.get_content(), "get_content")

    if content is None:
        logger.warning(f"Could not access content for '{driveitem.name}'")
        raise ValueError(f"Could not access content for '{driveitem.name}'")

    # Handle different content types
    if isinstance(content.value, bytes):
        content_bytes = content.value
    else:
        raise ValueError(f"Unsupported content type: {type(content.value)}")

    sections: list[TextSection | ImageSection] = []
    file_ext = driveitem.name.split(".")[-1]

    if "." + file_ext in ACCEPTED_IMAGE_FILE_EXTENSIONS:
        image_section, _ = store_image_and_create_section(
            image_data=content_bytes,
            file_id=driveitem.id,
            display_name=driveitem.name,
            file_origin=FileOrigin.CONNECTOR,
        )
        image_section.link = driveitem.web_url
        sections.append(image_section)
    else:
        file_text = extract_file_text(
            file=io.BytesIO(content_bytes),
            file_name=driveitem.name,
            break_on_unprocessable=False,
        )
        sections.append(TextSection(link=driveitem.web_url, text=file_text))

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
    SlimConnector,
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
        self._graph_client: GraphClient | None = None
        self.site_descriptors: list[SiteDescriptor] = self._extract_site_and_drive_info(
            sites
        )
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
            if "sites" in parts:
                sites_index = parts.index("sites")
                site_url = "/".join(parts[: sites_index + 2])
                remaining_parts = parts[sites_index + 2 :]

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
                        and any(
                            path_part == site_descriptor.folder_path
                            or path_part.startswith(site_descriptor.folder_path + "/")
                            for path_part in item.parent_reference.path.split("root:/")[
                                1
                            ].split("/")
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
                            and any(
                                path_part == site_descriptor.folder_path
                                or path_part.startswith(
                                    site_descriptor.folder_path + "/"
                                )
                                for path_part in item.parent_reference.path.split(
                                    "root:/"
                                )[1].split("/")
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

        site_descriptors = [
            SiteDescriptor(
                url=site.web_url or "",
                drive_name=None,
                folder_path=None,
            )
            for site in self._handle_paginated_sites(sites)
        ]
        return site_descriptors

    def _fetch_site_pages(
        self,
        site_descriptor: SiteDescriptor,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch SharePoint site pages (.aspx files) using the SharePoint Pages API."""
        # Exclude personal sites because GET personal site pages returns 404
        if "-my.sharepoint" in site_descriptor.url:
            return []

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
            pages_endpoint, headers=headers, params=params, timeout=REQUEST_TIMEOUT
        )
        response.raise_for_status()
        pages_data = response.json()
        all_pages = pages_data.get("value", [])

        # Handle pagination if there are more pages
        while "@odata.nextLink" in pages_data:
            next_url = pages_data["@odata.nextLink"]
            response = requests.get(next_url, headers=headers, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
            pages_data = response.json()
            all_pages.extend(pages_data.get("value", []))

        logger.debug(f"Found {len(all_pages)} site pages in {site_descriptor.url}")

        # Filter pages based on time window if specified
        if start is not None or end is not None:
            filtered_pages = []
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
                try:
                    doc = _convert_driveitem_to_document_with_permissions(
                        driveitem,
                        current_drive_name,
                        ctx,
                        self.graph_client,
                        include_permissions=include_permissions,
                    )
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

    def retrieve_all_slim_documents(
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
