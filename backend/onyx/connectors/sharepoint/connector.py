import html
import io
import os
import re
import time
from collections.abc import Generator
from datetime import datetime
from datetime import timezone
from typing import Any
from typing import cast
from urllib.parse import unquote

import msal  # type: ignore
import requests
from office365.graph_client import GraphClient  # type: ignore
from office365.onedrive.driveitems.driveItem import DriveItem  # type: ignore
from office365.onedrive.sites.site import Site  # type: ignore
from office365.onedrive.sites.sites_with_root import SitesWithRoot  # type: ignore
from office365.runtime.client_request import ClientRequestException  # type: ignore
from pydantic import BaseModel

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.configs.app_configs import SHAREPOINT_CONNECTOR_SIZE_THRESHOLD
from onyx.configs.constants import DocumentSource
from onyx.connectors.interfaces import GenerateDocumentsOutput
from onyx.connectors.interfaces import LoadConnector
from onyx.connectors.interfaces import PollConnector
from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.models import BasicExpertInfo
from onyx.connectors.models import ConnectorMissingCredentialError
from onyx.connectors.models import Document
from onyx.connectors.models import TextSection
from onyx.file_processing.extract_file_text import extract_file_text
from onyx.utils.logger import setup_logger


logger = setup_logger()


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


def _sleep_and_retry(query_obj: Any, method_name: str, max_retries: int = 3) -> Any:
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


def _convert_driveitem_to_document(
    driveitem: DriveItem,
    drive_name: str,
) -> Document | None:
    # Check file size before downloading
    try:
        size_value = getattr(driveitem, "size", None)
        if size_value is not None:
            file_size = int(size_value)
            if file_size > SHAREPOINT_CONNECTOR_SIZE_THRESHOLD:
                logger.warning(
                    f"File '{driveitem.name}' exceeds size threshold of {SHAREPOINT_CONNECTOR_SIZE_THRESHOLD} bytes. "
                    f"File size: {file_size} bytes. Skipping."
                )
                return None
        else:
            logger.warning(
                f"Could not access file size for '{driveitem.name}' Proceeding with download."
            )
    except (ValueError, TypeError, AttributeError) as e:
        logger.info(
            f"Could not access file size for '{driveitem.name}': {e}. Proceeding with download."
        )

    # Proceed with download if size is acceptable or not available
    content = _sleep_and_retry(driveitem.get_content(), "get_content")
    if content is None:
        logger.warning(f"Could not access content for '{driveitem.name}'")
        return None

    file_text = extract_file_text(
        file=io.BytesIO(content.value),
        file_name=driveitem.name,
        break_on_unprocessable=False,
    )

    doc = Document(
        id=driveitem.id,
        sections=[TextSection(link=driveitem.web_url, text=file_text)],
        source=DocumentSource.SHAREPOINT,
        semantic_identifier=driveitem.name,
        doc_updated_at=driveitem.last_modified_datetime.replace(tzinfo=timezone.utc),
        primary_owners=[
            BasicExpertInfo(
                display_name=driveitem.last_modified_by.user.displayName,
                email=driveitem.last_modified_by.user.email,
            )
        ],
        metadata={"drive": drive_name},
    )
    return doc


def _convert_sitepage_to_document(
    site_page: dict[str, Any], site_name: str | None
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

    doc = Document(
        id=site_page["id"],
        sections=[TextSection(link=web_url, text=page_text)],
        source=DocumentSource.SHAREPOINT,
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


class SharepointConnector(LoadConnector, PollConnector):
    def __init__(
        self,
        batch_size: int = INDEX_BATCH_SIZE,
        sites: list[str] = [],
        include_site_pages: bool = True,
    ) -> None:
        self.batch_size = batch_size
        self._graph_client: GraphClient | None = None
        self.site_descriptors: list[SiteDescriptor] = self._extract_site_and_drive_info(
            sites
        )
        self.msal_app: msal.ConfidentialClientApplication | None = None
        self.include_site_pages = include_site_pages

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
                        "Shared Documents" if drive.name == "Documents" else drive.name
                    )

                    # Filter items based on folder path if specified
                    if site_descriptor.folder_path:
                        # Filter items to ensure they're in the specified folder or its subfolders
                        # The path will be in format: /drives/{drive_id}/root:/folder/path
                        driveitems = [
                            item
                            for item in driveitems
                            if any(
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
                            if start
                            <= item.last_modified_datetime.replace(tzinfo=timezone.utc)
                            <= end
                        ]
                        logger.debug(
                            f"Found {len(driveitems)} items within time window in drive '{drive.name}'"
                        )

                    for item in driveitems:
                        final_driveitems.append((item, drive_name))

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

    def _fetch_sites(self) -> list[SiteDescriptor]:
        sites = self.graph_client.sites.get_all_sites().execute_query()

        if not sites:
            raise RuntimeError("No sites found in the tenant")

        site_descriptors = [
            SiteDescriptor(
                url=site.web_url,
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

    def _fetch_from_sharepoint(
        self, start: datetime | None = None, end: datetime | None = None
    ) -> GenerateDocumentsOutput:
        site_descriptors = self.site_descriptors or self._fetch_sites()

        # goes over all urls, converts them into Document objects and then yields them in batches
        doc_batch: list[Document] = []
        for site_descriptor in site_descriptors:
            # Fetch regular documents from document libraries
            driveitems = self._fetch_driveitems(site_descriptor, start=start, end=end)
            for driveitem, drive_name in driveitems:
                logger.debug(f"Processing: {driveitem.web_url}")

                # Convert driveitem to document with size checking
                doc = _convert_driveitem_to_document(driveitem, drive_name)
                if doc is not None:
                    doc_batch.append(doc)

                if len(doc_batch) >= self.batch_size:
                    yield doc_batch
                    doc_batch = []

            # Fetch SharePoint site pages (.aspx files)
            # Only fetch site pages if a folder is not specified since this processing
            # happens at a site-wide level + specifying a folder implies that the
            # user probably isn't looking for site pages
            specified_path = (
                site_descriptor.folder_path is not None
                or site_descriptor.drive_name is not None
            )
            if self.include_site_pages and not specified_path:
                site_pages = self._fetch_site_pages(
                    site_descriptor, start=start, end=end
                )
                for site_page in site_pages:
                    logger.debug(
                        f"Processing site page: {site_page.get('webUrl', site_page.get('name', 'Unknown'))}"
                    )
                    doc_batch.append(
                        _convert_sitepage_to_document(
                            site_page, site_descriptor.drive_name
                        )
                    )

                    if len(doc_batch) >= self.batch_size:
                        yield doc_batch
                        doc_batch = []

        yield doc_batch

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

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        sp_client_id = credentials["sp_client_id"]
        sp_client_secret = credentials["sp_client_secret"]
        sp_directory_id = credentials["sp_directory_id"]

        authority_url = f"https://login.microsoftonline.com/{sp_directory_id}"
        self.msal_app = msal.ConfidentialClientApplication(
            authority=authority_url,
            client_id=sp_client_id,
            client_credential=sp_client_secret,
        )
        self._graph_client = GraphClient(self._acquire_token)
        return None

    def load_from_state(self) -> GenerateDocumentsOutput:
        return self._fetch_from_sharepoint()

    def poll_source(
        self, start: SecondsSinceUnixEpoch, end: SecondsSinceUnixEpoch
    ) -> GenerateDocumentsOutput:
        start_datetime = datetime.fromtimestamp(start, timezone.utc)
        end_datetime = datetime.fromtimestamp(end, timezone.utc)
        return self._fetch_from_sharepoint(start=start_datetime, end=end_datetime)


if __name__ == "__main__":
    connector = SharepointConnector(sites=os.environ["SHAREPOINT_SITES"].split(","))

    connector.load_credentials(
        {
            "sp_client_id": os.environ["SHAREPOINT_CLIENT_ID"],
            "sp_client_secret": os.environ["SHAREPOINT_CLIENT_SECRET"],
            "sp_directory_id": os.environ["SHAREPOINT_CLIENT_DIRECTORY_ID"],
        }
    )
    document_batches = connector.load_from_state()
    print(next(document_batches))
