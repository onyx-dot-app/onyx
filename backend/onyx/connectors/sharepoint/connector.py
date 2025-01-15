import io
import os
from dataclasses import dataclass
from dataclasses import field
from datetime import datetime
from datetime import timezone
from typing import Any
from typing import Optional

import msal  # type: ignore
from office365.graph_client import GraphClient  # type: ignore
from office365.onedrive.driveitems.driveItem import DriveItem  # type: ignore
from office365.onedrive.sites.site import Site  # type: ignore

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


@dataclass
class SiteData:
    url: str | None
    folder: Optional[str]
    sites: list = field(default_factory=list)
    driveitems: list = field(default_factory=list)


def _convert_driveitem_to_document(
    driveitem: DriveItem,
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
        metadata={},
    )
    return doc


class SharepointConnector(LoadConnector, PollConnector):
    def __init__(
        self,
        batch_size: int = INDEX_BATCH_SIZE,
        sites: list[str] = [],
    ) -> None:
        self.batch_size = batch_size
        self.graph_client: GraphClient | None = None
        self.site_data: list[SiteData] = self._extract_site_and_folder(sites)

    @staticmethod
    def _extract_site_and_folder(site_urls: list[str]) -> list[SiteData]:
        site_data_list = []
        for url in site_urls:
            parts = url.strip().split("/")
            if "sites" in parts:
                sites_index = parts.index("sites")
                site_url = "/".join(parts[: sites_index + 2])
                folder = (
                    parts[sites_index + 2] if len(parts) > sites_index + 2 else None
                )
                site_data_list.append(
                    SiteData(url=site_url, folder=folder, sites=[], driveitems=[])
                )
        return site_data_list

    def _populate_sitedata_driveitems(
        self,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> None:
        filter_str = ""
        if start is not None and end is not None:
            filter_str = f"last_modified_datetime ge {start.isoformat()} and last_modified_datetime le {end.isoformat()}"

        for element in self.site_data:
            sites: list[Site] = []
            for site in element.sites:
                site_sublist = site.lists.get().execute_query()
                sites.extend(site_sublist)

            for site in sites:
                try:
                    query = site.drive.root.get_files(True, 1000)
                    if filter_str:
                        query = query.filter(filter_str)
                    driveitems = query.execute_query()
                    if element.folder:
                        filtered_driveitems = [
                            item
                            for item in driveitems
                            if element.folder in item.parent_reference.path
                        ]
                        element.driveitems.extend(filtered_driveitems)
                    else:
                        element.driveitems.extend(driveitems)

                except Exception:
                    # Sites include things that do not contain .drive.root so this fails
                    # but this is fine, as there are no actually documents in those
                    pass

    def _populate_sitedata_sites(self) -> None:
        if self.graph_client is None:
            raise ConnectorMissingCredentialError("Sharepoint")

        if self.site_data:
            for element in self.site_data:
                element.sites = [
                    self.graph_client.sites.get_by_url(element.url)
                    .get()
                    .execute_query()
                ]
        else:
            sites = self.graph_client.sites.get_all().execute_query()
            self.site_data = [
                SiteData(url=None, folder=None, sites=sites, driveitems=[])
            ]

    def _fetch_from_sharepoint(
        self, start: datetime | None = None, end: datetime | None = None
    ) -> GenerateDocumentsOutput:
        if self.graph_client is None:
            raise ConnectorMissingCredentialError("Sharepoint")

        self._populate_sitedata_sites()
        self._populate_sitedata_driveitems(start=start, end=end)

        # goes over all urls, converts them into Document objects and then yields them in batches
        doc_batch: list[Document] = []
        for element in self.site_data:
            for driveitem in element.driveitems:
                logger.debug(f"Processing: {driveitem.web_url}")
                doc_batch.append(_convert_driveitem_to_document(driveitem))

                if len(doc_batch) >= self.batch_size:
                    yield doc_batch
                    doc_batch = []
        yield doc_batch

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        sp_client_id = credentials["sp_client_id"]
        sp_client_secret = credentials["sp_client_secret"]
        sp_directory_id = credentials["sp_directory_id"]

        def _acquire_token_func() -> dict[str, Any]:
            """
            Acquire token via MSAL
            """
            authority_url = f"https://login.microsoftonline.com/{sp_directory_id}"
            app = msal.ConfidentialClientApplication(
                authority=authority_url,
                client_id=sp_client_id,
                client_credential=sp_client_secret,
            )
            token = app.acquire_token_for_client(
                scopes=["https://graph.microsoft.com/.default"]
            )
            return token

        self.graph_client = GraphClient(_acquire_token_func)
        return None

    def load_from_state(self) -> GenerateDocumentsOutput:
        return self._fetch_from_sharepoint()

    def poll_source(
        self, start: SecondsSinceUnixEpoch, end: SecondsSinceUnixEpoch
    ) -> GenerateDocumentsOutput:
        start_datetime = datetime.utcfromtimestamp(start)
        end_datetime = datetime.utcfromtimestamp(end)
        return self._fetch_from_sharepoint(start=start_datetime, end=end_datetime)


if __name__ == "__main__":
    connector = SharepointConnector(sites=os.environ["SITES"].split(","))

    connector.load_credentials(
        {
            "sp_client_id": os.environ["SP_CLIENT_ID"],
            "sp_client_secret": os.environ["SP_CLIENT_SECRET"],
            "sp_directory_id": os.environ["SP_CLIENT_DIRECTORY_ID"],
        }
    )
    document_batches = connector.load_from_state()
    print(next(document_batches))
