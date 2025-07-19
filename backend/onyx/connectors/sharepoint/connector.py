import base64
import io
import os
from collections.abc import Generator
from datetime import datetime
from datetime import timezone
from typing import Any
from urllib.parse import unquote

import msal  # type: ignore[import-untyped]
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.serialization import pkcs12
from office365.graph_client import GraphClient  # type: ignore[import-untyped]
from office365.onedrive.driveitems.driveItem import DriveItem  # type: ignore[import-untyped]
from office365.onedrive.sites.site import Site  # type: ignore[import-untyped]
from office365.onedrive.sites.sites_with_root import SitesWithRoot  # type: ignore[import-untyped]
from office365.runtime.auth.token_response import TokenResponse  # type: ignore[import-untyped]
from office365.sharepoint.client_context import ClientContext  # type: ignore[import-untyped]
from pydantic import BaseModel

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.configs.constants import DocumentSource
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.interfaces import GenerateDocumentsOutput
from onyx.connectors.interfaces import GenerateSlimDocumentOutput
from onyx.connectors.interfaces import IndexingHeartbeatInterface
from onyx.connectors.interfaces import LoadConnector
from onyx.connectors.interfaces import PollConnector
from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.interfaces import SlimConnector
from onyx.connectors.models import BasicExpertInfo
from onyx.connectors.models import ConnectorMissingCredentialError
from onyx.connectors.models import Document
from onyx.connectors.models import SlimDocument
from onyx.connectors.models import TextSection
from onyx.connectors.sharepoint.utils import get_sharepoint_external_access
from onyx.file_processing.extract_file_text import extract_file_text
from onyx.utils.logger import setup_logger

logger = setup_logger()
SLIM_BATCH_SIZE = 1000


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


def load_certificate_from_pfx(
    pfx_data: bytes, password: str
) -> dict[str, bytes | str] | None:
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

        return {
            "private_key": key_pem,
            "thumbprint": certificate.fingerprint(hashes.SHA1()).hex(),
        }
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


def _convert_driveitem_to_document(
    driveitem: DriveItem,
    drive_name: str,
) -> Document:

    if driveitem.name is None:
        raise ValueError("DriveItem name is required")
    if driveitem.id is None:
        raise ValueError("DriveItem ID is required")

    content = driveitem.get_content().execute_query().value

    if content is None:
        raise ValueError("DriveItem content is not available")

    # Handle different content types
    if isinstance(content, bytes):
        content_bytes = content
    elif isinstance(content, str):
        content_bytes = content.encode("utf-8")
    else:
        raise ValueError(f"Unsupported content type: {type(content)}")

    file_text = extract_file_text(
        file=io.BytesIO(content_bytes),
        file_name=driveitem.name,
        break_on_unprocessable=False,
    )

    doc = Document(
        id=driveitem.id,
        sections=[TextSection(link=driveitem.web_url, text=file_text)],
        source=DocumentSource.SHAREPOINT,
        semantic_identifier=driveitem.name,
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


def _convert_driveitem_to_slim_document(
    driveitem: DriveItem,
    drive_name: str,
    ctx: ClientContext,
    graph_client: GraphClient,
) -> SlimDocument:
    if driveitem.id is None:
        raise ValueError("DriveItem ID is required")

    external_access = get_sharepoint_external_access(
        driveitem, drive_name, ctx, graph_client
    )

    return SlimDocument(
        id=driveitem.id,
        external_access=external_access,
    )


class SharepointConnector(LoadConnector, PollConnector, SlimConnector):
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
        self.sp_tenant_domain: str | None = None

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
                    logger.warning(f"Failed to process drive: {str(e)}")

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

    def _fetch_from_sharepoint(
        self,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> GenerateDocumentsOutput:
        site_descriptors = self.site_descriptors or self.fetch_sites()

        # goes over all urls, converts them into Document objects and then yields them in batches
        doc_batch: list[Document] = []
        for site_descriptor in site_descriptors:
            driveitems = self._fetch_driveitems(site_descriptor, start=start, end=end)
            for driveitem, drive_name in driveitems:
                try:
                    logger.debug(f"Processing: {driveitem.web_url}")
                    doc_batch.append(
                        _convert_driveitem_to_document(driveitem, drive_name)
                    )
                except Exception as e:
                    logger.warning(f"Failed to process driveitem: {str(e)}")

                if len(doc_batch) >= self.batch_size:
                    yield doc_batch
                    doc_batch = []
        yield doc_batch

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
        yield doc_batch

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        auth_method = credentials.get("authentication_method", "client_secret")
        sp_client_id = credentials.get("sp_client_id")
        sp_client_secret = credentials.get("sp_client_secret")
        sp_directory_id = credentials.get("sp_directory_id")
        sp_private_key = credentials.get("sp_private_key")
        sp_certificate_password = credentials.get("sp_certificate_password")
        sp_tenant_domain = credentials.get("sp_tenant_domain")

        authority_url = f"https://login.microsoftonline.com/{sp_directory_id}"
        if auth_method == "certificate":
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
                client_credential=certificate_data,
            )
        elif sp_client_secret:
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
        self.sp_tenant_domain = sp_tenant_domain
        return None

    def load_from_state(self) -> GenerateDocumentsOutput:
        return self._fetch_from_sharepoint()

    def poll_source(
        self, start: SecondsSinceUnixEpoch, end: SecondsSinceUnixEpoch
    ) -> GenerateDocumentsOutput:
        start_datetime = datetime.fromtimestamp(start, timezone.utc)
        end_datetime = datetime.fromtimestamp(end, timezone.utc)
        return self._fetch_from_sharepoint(start=start_datetime, end=end_datetime)

    def retrieve_all_slim_documents(
        self,
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,
        callback: IndexingHeartbeatInterface | None = None,
    ) -> GenerateSlimDocumentOutput:

        yield from self._fetch_slim_documents_from_sharepoint()


if __name__ == "__main__":
    connector = SharepointConnector(sites=os.environ["SHAREPOINT_SITES"].split(","))

    connector.load_credentials(
        {
            "sp_client_id": os.environ["SHAREPOINT_CLIENT_ID"],
            "sp_client_secret": os.environ["SHAREPOINT_CLIENT_SECRET"],
            "sp_directory_id": os.environ["SHAREPOINT_CLIENT_DIRECTORY_ID"],
            "authentication_method": "client_secret",
        }
    )
    document_batches = connector.load_from_state()
    logger.info(next(document_batches))
