from datetime import datetime
from datetime import timezone
from typing import Any
from typing import List
from typing import Optional

import requests

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.configs.constants import DocumentSource
from onyx.connectors.cross_connector_utils.rate_limit_wrapper import (
    rate_limit_builder,
)
from onyx.connectors.document360.utils import flatten_child_categories
from onyx.connectors.interfaces import GenerateDocumentsOutput
from onyx.connectors.interfaces import LoadConnector
from onyx.connectors.interfaces import PollConnector
from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.models import BasicExpertInfo
from onyx.connectors.models import ConnectorMissingCredentialError
from onyx.connectors.models import Document
from onyx.connectors.models import TextSection
from onyx.file_processing.html_utils import parse_html_page_basic
from onyx.utils.retry_wrapper import retry_builder

# Limitations and Potential Improvements
# 1. The "Categories themselves contain potentially relevant information" but they're not pulled in
# 2. Only the HTML Articles are supported, Document360 also has a Markdown and "Block" format
# 3. The contents are not as cleaned up as other HTML connectors

DOCUMENT360_BASE_URL = "https://portal.document360.io"
DOCUMENT360_API_BASE_URL = "https://apihub.document360.io/v2"


class Document360Connector(LoadConnector, PollConnector):
    def __init__(
        self,
        workspace: str,
        categories: List[str] | None = None,
        batch_size: int = INDEX_BATCH_SIZE,
        portal_id: Optional[str] = None,
        api_token: Optional[str] = None,
    ) -> None:
        self.portal_id = portal_id
        self.workspace = workspace
        self.categories = categories
        self.batch_size = batch_size
        self.api_token = api_token

    def load_credentials(self, credentials: dict[str, Any]) -> Optional[dict[str, Any]]:
        self.api_token = credentials.get("document360_api_token")
        self.portal_id = credentials.get("portal_id")
        return None

    # rate limiting set based on the enterprise plan: https://apidocs.document360.com/apidocs/rate-limiting
    # NOTE: retry will handle cases where user is not on enterprise plan - we will just hit the rate limit
    # and then retry after a period
    @retry_builder()
    @rate_limit_builder(max_calls=100, period=60)
    def _make_request(self, endpoint: str, params: Optional[dict] = None) -> Any:
        if not self.api_token:
            raise ConnectorMissingCredentialError("Document360")

        headers = {"accept": "application/json", "api_token": self.api_token}

        response = requests.get(
            f"{DOCUMENT360_API_BASE_URL}/{endpoint}", headers=headers, params=params
        )
        response.raise_for_status()

        return response.json()["data"]

    def _get_workspace_id_by_name(self) -> str:
        projects = self._make_request("ProjectVersions")
        workspace_id = next(
            (
                project["id"]
                for project in projects
                if project["version_code_name"] == self.workspace
            ),
            None,
        )
        if workspace_id is None:
            raise ValueError("Not able to find Workspace ID by the user provided name")

        return workspace_id

    def _get_articles_with_category(self, workspace_id: str) -> Any:
        all_categories = self._make_request(
            f"ProjectVersions/{workspace_id}/categories"
        )
        articles_with_category = []

        for category in all_categories:
            if not self.categories or category["name"] in self.categories:
                for article in category["articles"]:
                    articles_with_category.append(
                        {"id": article["id"], "category_name": category["name"]}
                    )
                for child_category in category["child_categories"]:
                    all_nested_categories = flatten_child_categories(child_category)
                    for nested_category in all_nested_categories:
                        for article in nested_category["articles"]:
                            articles_with_category.append(
                                {
                                    "id": article["id"],
                                    "category_name": nested_category["name"],
                                }
                            )

        return articles_with_category

    def _process_articles(
        self, start: datetime | None = None, end: datetime | None = None
    ) -> GenerateDocumentsOutput:
        if self.api_token is None:
            raise ConnectorMissingCredentialError("Document360")

        workspace_id = self._get_workspace_id_by_name()
        articles = self._get_articles_with_category(workspace_id)

        doc_batch: List[Document] = []

        for article in articles:
            article_details = self._make_request(
                f"Articles/{article['id']}", {"langCode": "en"}
            )

            updated_at = datetime.strptime(
                article_details["modified_at"], "%Y-%m-%dT%H:%M:%S.%fZ"
            ).replace(tzinfo=timezone.utc)
            if start is not None and updated_at < start:
                continue
            if end is not None and updated_at > end:
                continue

            authors = [
                BasicExpertInfo(
                    display_name=author.get("name"), email=author["email_id"]
                )
                for author in article_details.get("authors", [])
                if author["email_id"]
            ]

            doc_link = (
                article_details["url"]
                if article_details.get("url")
                else f"{DOCUMENT360_BASE_URL}/{self.portal_id}/document/v1/view/{article['id']}"
            )

            html_content = article_details["html_content"]
            article_content = (
                parse_html_page_basic(html_content) if html_content is not None else ""
            )
            doc_text = (
                f"{article_details.get('description', '')}\n{article_content}".strip()
            )

            document = Document(
                id=article_details["id"],
                sections=[TextSection(link=doc_link, text=doc_text)],
                source=DocumentSource.DOCUMENT360,
                semantic_identifier=article_details["title"],
                doc_updated_at=updated_at,
                primary_owners=authors,
                metadata={
                    "workspace": self.workspace,
                    "category": article["category_name"],
                },
            )

            doc_batch.append(document)

            if len(doc_batch) >= self.batch_size:
                yield doc_batch
                doc_batch = []

        if doc_batch:
            yield doc_batch

    def load_from_state(self) -> GenerateDocumentsOutput:
        return self._process_articles()

    def poll_source(
        self, start: SecondsSinceUnixEpoch, end: SecondsSinceUnixEpoch
    ) -> GenerateDocumentsOutput:
        start_datetime = datetime.fromtimestamp(start, tz=timezone.utc)
        end_datetime = datetime.fromtimestamp(end, tz=timezone.utc)
        return self._process_articles(start_datetime, end_datetime)


if __name__ == "__main__":
    import time
    import os

    document360_connector = Document360Connector(os.environ["DOCUMENT360_WORKSPACE"])
    document360_connector.load_credentials(
        {
            "portal_id": os.environ["DOCUMENT360_PORTAL_ID"],
            "document360_api_token": os.environ["DOCUMENT360_API_TOKEN"],
        }
    )

    current = time.time()
    one_year_ago = current - 24 * 60 * 60 * 360
    latest_docs = document360_connector.poll_source(one_year_ago, current)

    for doc in latest_docs:
        print(doc)
