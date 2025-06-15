import asyncio
import os
from collections.abc import Generator
from datetime import datetime
from typing import Any, Optional
from urllib.parse import quote

from azure.core.credentials import AccessToken
from bs4 import BeautifulSoup
from kiota_abstractions.base_request_configuration import RequestConfiguration
from msgraph import GraphServiceClient
from msgraph.generated.models.onenote_page import OnenotePage
from msgraph.generated.users.item.onenote.pages.pages_request_builder import (
    PagesRequestBuilder,
)

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.configs.constants import DocumentSource
from onyx.connectors.cross_connector_utils.miscellaneous_utils import (
    get_oauth_callback_uri,
)
from onyx.connectors.interfaces import (
    GenerateDocumentsOutput,
    LoadConnector,
    OAuthConnector,
    PollConnector,
    SecondsSinceUnixEpoch,
)
from onyx.connectors.models import ConnectorMissingCredentialError, Document, Section
from onyx.file_processing.html_utils import web_html_cleanup
from onyx.utils.logger import setup_logger
from onyx.utils.retry_wrapper import request_with_retries

logger = setup_logger()

GRAPH_SCOPES = ["Notes.Read", "Notes.Read.All", "offline_access"]


class OneNoteConnector(LoadConnector, PollConnector, OAuthConnector):
    """Connector for loading documents from OneNote using OAuth
    TODO: Figure out how to do the refresh token logic
    """

    class AdditionalOauthKwargs(OAuthConnector.AdditionalOauthKwargs):
        pass
        # tenant_id: str = Field(
        #     title="Azure AD Tenant ID",
        #     description="The tenant ID from Azure Active Directory"
        # )

    def __init__(self, batch_size: int = INDEX_BATCH_SIZE) -> None:
        self.batch_size = batch_size
        self.indexed_files: set[str] = set()
        self.graph_client: Optional[GraphServiceClient] = None

    @classmethod
    def oauth_id(cls) -> DocumentSource:
        return DocumentSource.ONE_NOTE

    @classmethod
    def oauth_authorization_url(
        cls, base_domain: str, state: str, additional_kwargs: dict[str, str]
    ) -> str:
        # we could consider separating the client id and secret for one drive and one note
        # but for now we will use the same client id and secret for both for simplicity
        client_id = os.environ.get("ONE_DRIVE_CLIENT_ID")
        if not client_id:
            raise ValueError("ONE_DRIVE_CLIENT_ID environment variable must be set")

        oauth_kwargs = cls.AdditionalOauthKwargs(**additional_kwargs)
        callback_uri = get_oauth_callback_uri(base_domain, "one_note")

        return (
            # maybe need tenant_id instead of common
            f"https://login.microsoftonline.com/common/oauth2/v2.0/authorize"
            f"?client_id={client_id}"
            f"&response_type=code"
            f"&redirect_uri={quote(callback_uri)}"
            f"&response_mode=query"
            f"&scope={' '.join(GRAPH_SCOPES)}"
            f"&state={state}"
        )

    @classmethod
    def oauth_code_to_token(
        cls, base_domain: str, code: str, additional_kwargs: dict[str, str]
    ) -> dict[str, Any]:
        client_id = os.environ.get("ONE_DRIVE_CLIENT_ID")
        client_secret = os.environ.get("ONE_DRIVE_CLIENT_SECRET")

        if not client_id:
            raise ValueError("ONE_DRIVE_CLIENT_ID environment variable must be set")
        if not client_secret:
            raise ValueError("ONE_DRIVE_CLIENT_SECRET environment variable must be set")

        oauth_kwargs = cls.AdditionalOauthKwargs(**additional_kwargs)
        callback_uri = get_oauth_callback_uri(base_domain, "one_note")

        # TODO: maybe need tenant_id instead of common
        token_url = "https://login.microsoftonline.com/common/oauth2/v2.0/token"

        data = {
            "client_id": client_id,
            "client_secret": client_secret,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": callback_uri,
        }
        headers = {"Content-Type": "application/x-www-form-urlencoded"}

        response = request_with_retries(
            method="POST",
            url=token_url,
            headers=headers,
            data=data,
            backoff=0,
            delay=0.1,
        )

        if not response.ok:
            raise RuntimeError(f"Failed to exchange code for token: {response.text}")

        token_data = response.json()

        return {
            "access_token": token_data["access_token"],
            "refresh_token": token_data["refresh_token"],
            "expires_in": str(token_data["expires_in"] - 100),
            "time_requested": str(datetime.now().timestamp()),
        }

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        """Initialize Microsoft Graph client with OAuth credentials"""

        # Create a pseudo TokenCredential object that wraps the access token string
        class PseudoTokenCredential:
            def __init__(self, token: str, refresh_token: str):
                self._token = token
                self._refresh_token = refresh_token

            def get_token(self, *scopes: str, **kwargs) -> AccessToken:
                return AccessToken(token=self._token, expires_on=1234567890)

            def get_refresh_token(self) -> str:
                return self._refresh_token

        # check if the token expired, if it did refresh it.
        # if it didn't, use it.
        has_refreshed = False
        if float(credentials["expires_in"]) < float(datetime.now().timestamp()) - float(
            credentials["time_requested"]
        ):
            credentials = self.refresh_token(credentials["refresh_token"])
            has_refreshed = True

        azure_credentials = PseudoTokenCredential(
            credentials["access_token"], credentials["refresh_token"]
        )

        try:
            self.graph_client = GraphServiceClient(credentials=azure_credentials)

            if has_refreshed:
                return credentials
            else:
                return None

        except Exception as e:
            logger.error(f"Error loading OneNote credentials: {e}")
            raise ConnectorMissingCredentialError("OneNote")

    def refresh_token(self, refresh_token: str) -> dict[str, Any]:
        """Refresh the access token using the refresh token"""
        logger.info("Refreshing OneNote token")

        client_id = os.environ.get("ONE_DRIVE_CLIENT_ID")
        client_secret = os.environ.get("ONE_DRIVE_CLIENT_SECRET")

        # TODO: maybe need tenant_id instead of common
        token_url = "https://login.microsoftonline.com/common/oauth2/v2.0/token"

        data = {
            "client_id": client_id,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "scope": " ".join(GRAPH_SCOPES),
            "client_secret": client_secret,
        }
        headers = {"Content-Type": "application/x-www-form-urlencoded"}

        response = request_with_retries(
            method="POST",
            url=token_url,
            headers=headers,
            data=data,
            backoff=0,
            delay=0.1,
        )

        if not response.ok:
            raise RuntimeError(f"Failed to exchange code for token: {response.text}")

        token_data = response.json()

        return {
            "access_token": token_data["access_token"],
            "refresh_token": token_data["refresh_token"],
            # make sure we refresh the token before it expires
            "expires_in": str(token_data["expires_in"] - 100),
            "time_requested": str(datetime.now().timestamp()),
        }

    def _process_file(self, page: OnenotePage) -> Optional[Document]:
        """Process a single OneDrive file into a Document"""
        try:
            if not page.id or not page.title:
                return None

            # Download and read file content
            content = self._get_file_content(page)
            if not content:
                return None

            sections = [
                Section(text=content, link=page.links.one_note_web_url.href or "")
            ]

            metadata = {"title": page.title}

            return Document(
                id=page.id,
                source=DocumentSource.ONE_NOTE,
                semantic_identifier=page.title,
                sections=sections,
                metadata=metadata,
            )

        except Exception as e:
            logger.error(f"Error processing OneDrive file: {e}")
            return None

    def _get_file_content(self, page: OnenotePage) -> Optional[str]:
        """Download and extract content from a OneNote page"""
        try:
            if not self.graph_client:
                raise ValueError("Graph client not initialized")

            # Download file content
            loop = asyncio.get_event_loop()

            content_url = page.content_url
            # TODO: make this more programmatic to get the user information...
            # URL looks like this `https://graph.microsoft.com/v1.0/users/15a0bdcb-15e8-4982-a7c9-e526aad42aa0/onenote/pages/1-b0c293dc6436430dbe05179e95d1d5ec!69-3b189091-cf77-4fb6-84cd-8c7d2d910895/content`
            # extract user and page id using regex
            pieces = content_url.split("/")
            user_id = pieces[5]
            page_id = pieces[8]

            page_content = loop.run_until_complete(
                self.graph_client.users.by_user_id(user_id)
                .onenote.pages.by_onenote_page_id(page_id)
                .content.get()
            )

            soup = BeautifulSoup(page_content, "html.parser")
            parsed_html = web_html_cleanup(soup)
            return parsed_html.cleaned_text

        except Exception as e:
            logger.error(f"Error getting file content: {e}")
            return None

    def _list_files(
        self,
        start: Optional[SecondsSinceUnixEpoch] = None,
        end: Optional[SecondsSinceUnixEpoch] = None,
    ) -> Generator[OnenotePage, None, None]:
        """List OneNote files, optionally filtered by time range"""
        try:
            if not self.graph_client:
                raise ValueError("Graph client not initialized")
            loop = asyncio.get_event_loop()
            all_pages = []

            pages = loop.run_until_complete(self.graph_client.me.onenote.pages.get())
            all_pages.extend(pages.value)

            while pages.odata_next_link:
                logger.info(
                    f"Fetching next page of OneNote pages: {pages.odata_next_link}"
                )

                # extract the skip token from the url
                skip_count = pages.odata_next_link.split("skip=")[1]
                query_params = (
                    PagesRequestBuilder.PagesRequestBuilderGetQueryParameters(
                        skip=skip_count
                    )
                )

                request_configuration = RequestConfiguration(
                    query_parameters=query_params
                )

                pages = loop.run_until_complete(
                    self.graph_client.me.onenote.pages.get(
                        request_configuration=request_configuration
                    )
                )
                all_pages.extend(pages.value)

            return all_pages

        except Exception as e:
            logger.error(f"Error listing OneDrive files: {e}")
            raise

    def poll_source(
        self, start: SecondsSinceUnixEpoch, end: SecondsSinceUnixEpoch
    ) -> Generator[list[Document], None, None]:
        """Poll for OneDrive files modified within the given time period"""
        try:
            current_batch = []

            for page in self._list_files(start, end):
                if not page.id or page.id in self.indexed_files:
                    continue

                doc = self._process_file(page)
                if doc:
                    current_batch.append(doc)
                    self.indexed_files.add(page.id)

                    if len(current_batch) >= self.batch_size:
                        yield current_batch
                        current_batch = []

            if current_batch:
                yield current_batch

        except Exception as e:
            logger.error(f"Error polling OneDrive connector: {e}")
            raise

    def load_from_state(self) -> GenerateDocumentsOutput:
        """Load and process all OneDrive files"""
        try:
            current_batch = []

            for page in self._list_files():
                if not page.id or page.id in self.indexed_files:
                    continue

                doc = self._process_file(page)
                if doc:
                    current_batch.append(doc)
                    self.indexed_files.add(page.id)

                    if len(current_batch) >= self.batch_size:
                        yield current_batch
                        current_batch = []

            if current_batch:
                yield current_batch

        except Exception as e:
            logger.error(f"Error in OneDrive connector: {e}")
            raise


def test_connector():
    """Simple test function for the connector"""
    # Add test credentials
    test_credentials = {
        "access_token": "",
        "refresh_token": "",
        "expires_in": "-100",
        "time_requested": str(datetime.now().timestamp()),
    }

    connector = OneNoteConnector(batch_size=10)
    connector.load_credentials(test_credentials)

    total_docs = 0
    total_batches = 0

    try:
        for batch in connector.load_from_state():
            total_docs += len(batch)
            total_batches += 1

            if total_batches == 1:
                doc = batch[0]
                print("\nFirst document example:")
                print(f"ID: {doc.id}")
                print(f"Name: {doc.semantic_identifier}")
                print(f"Content preview: {doc.sections[0].text[:200]}...")
                print(f"Metadata: {doc.metadata}")

        print("\nProcessing complete:")
        print(f"Total documents: {total_docs}")
        print(f"Total batches: {total_batches}")
        print(f"Average batch size: {total_docs / total_batches:.1f}")

    except Exception as e:
        logger.error(f"Test failed: {e}")
        raise


if __name__ == "__main__":
    test_connector()
