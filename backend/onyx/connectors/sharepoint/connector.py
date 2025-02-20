import io
import os
from datetime import datetime
from datetime import timezone
from typing import Any
from urllib.parse import unquote

import msal  # type: ignore
from office365.graph_client import GraphClient  # type: ignore
from office365.onedrive.driveitems.driveItem import DriveItem  # type: ignore
from pydantic import BaseModel

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.configs.constants import DocumentSource
from onyx.connectors.interfaces import GenerateDocumentsOutput
from onyx.connectors.interfaces import LoadConnector
from onyx.connectors.interfaces import PollConnector
from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.models import BasicExpertInfo
from onyx.connectors.models import ConnectorMissingCredentialError
from onyx.connectors.models import Document
from onyx.connectors.models import Section
from onyx.file_processing.extract_file_text import extract_file_text
from onyx.utils.logger import setup_logger


logger = setup_logger()


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


def _convert_driveitem_to_document(
    driveitem: DriveItem,
    drive_name: str,
) -> Document:
    file_text = extract_file_text(
        file=io.BytesIO(driveitem.get_content().execute_query().value),
        file_name=driveitem.name,
        break_on_unprocessable=False,
    )

    doc = Document(
        id=driveitem.id,
        sections=[Section(link=driveitem.web_url, text=file_text)],
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


class SharepointConnector(LoadConnector, PollConnector):
    def __init__(
        self,
        batch_size: int = INDEX_BATCH_SIZE,
        sites: list[str] = [],
    ) -> None:
        self.batch_size = batch_size
        self._graph_client: GraphClient | None = None
        self.site_descriptors: list[SiteDescriptor] = self._extract_site_and_drive_info(
            sites
        )
        self.msal_app: msal.ConfidentialClientApplication | None = None

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
                    logger.warning(f"Failed to process drive: {str(e)}")

        except Exception as e:
            # Sites include things that do not contain drives so this fails
            # but this is fine, as there are no actual documents in those
            logger.warning(f"Failed to process site: {str(e)}")

        return final_driveitems

    def _fetch_sites(self) -> list[SiteDescriptor]:
        sites = self.graph_client.sites.get_all().execute_query()
        site_descriptors = [
            SiteDescriptor(
                url=sites.resource_url,
                drive_name=None,
                folder_path=None,
            )
        ]
        return site_descriptors

    def _fetch_from_sharepoint(
        self, start: datetime | None = None, end: datetime | None = None
    ) -> GenerateDocumentsOutput:
        site_descriptors = self.site_descriptors or self._fetch_sites()

        # goes over all urls, converts them into Document objects and then yields them in batches
        doc_batch: list[Document] = []
        for site_descriptor in site_descriptors:
            driveitems = self._fetch_driveitems(site_descriptor, start=start, end=end)
            for driveitem, drive_name in driveitems:
                logger.debug(f"Processing: {driveitem.web_url}")
                doc_batch.append(_convert_driveitem_to_document(driveitem, drive_name))

                if len(doc_batch) >= self.batch_size:
                    yield doc_batch
                    doc_batch = []
        yield doc_batch

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

        def _acquire_token_func() -> dict[str, Any]:
            """
            Acquire token via MSAL
            """
            if self.msal_app is None:
                raise RuntimeError("MSAL app is not initialized")

            token = self.msal_app.acquire_token_for_client(
                scopes=["https://graph.microsoft.com/.default"]
            )
            return token

        self._graph_client = GraphClient(_acquire_token_func)
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
